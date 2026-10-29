"""Minimal lossless protobuf-table reader/writer for language field 2."""
from __future__ import annotations

from dataclasses import dataclass


def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while pos < len(data) and shift < 70:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, pos
        shift += 7
    raise ValueError("malformed protobuf varint")


def varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


@dataclass(frozen=True)
class Field:
    number: int
    wire: int
    raw: bytes
    value: bytes | int


def fields(data: bytes):
    pos = 0
    while pos < len(data):
        start = pos
        tag, pos = read_varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError("invalid protobuf field number 0")
        if wire == 0:
            value, pos = read_varint(data, pos)
        elif wire == 1:
            end = pos + 8
            if end > len(data): raise ValueError("truncated fixed64")
            value, pos = data[pos:end], end
        elif wire == 2:
            size, pos = read_varint(data, pos)
            end = pos + size
            if end > len(data): raise ValueError("truncated length-delimited field")
            value, pos = data[pos:end], end
        elif wire == 5:
            end = pos + 4
            if end > len(data): raise ValueError("truncated fixed32")
            value, pos = data[pos:end], end
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        yield Field(number, wire, data[start:pos], value)


def length_field(number: int, value: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(value)) + value


def table_header(data: bytes) -> tuple[bytes, bytes]:
    if len(data) < 4:
        raise ValueError("table missing 4-byte header length")
    size = int.from_bytes(data[:4], "little")
    end = 4 + size
    if end > len(data):
        raise ValueError("table header length exceeds file")
    return data[:end], data[end:]


def table_rows(data: bytes):
    header, body = table_header(data)
    del header
    for field in fields(body):
        if field.number != 1 or field.wire != 2:
            raise ValueError("unexpected top-level table field")
        yield field.value


def _rewrite_section_entry(raw_entry: bytes, offset: int, size: int) -> bytes:
    """Update the offset/size pair in a header map entry, retaining unknown fields."""
    output = bytearray()
    key_seen = False
    offset_seen = size_seen = False
    for entry_field in fields(raw_entry):
        if entry_field.number == 1 and entry_field.wire == 0:
            output += entry_field.raw
            key_seen = True
        elif entry_field.number == 2 and entry_field.wire == 2:
            value = bytearray()
            for value_field in fields(bytes(entry_field.value)):
                if value_field.number == 1 and value_field.wire == 0:
                    if offset and not offset_seen:
                        value += varint(8) + varint(offset)
                    offset_seen = True
                elif value_field.number == 2 and value_field.wire == 0:
                    if size and not size_seen:
                        value += varint(16) + varint(size)
                    size_seen = True
                else:
                    value += value_field.raw
            if not offset_seen and offset:
                value += varint(8) + varint(offset)
            if not size_seen and size:
                value += varint(16) + varint(size)
            output += length_field(2, bytes(value))
        else:
            output += entry_field.raw
    if not key_seen:
        raise ValueError("section index entry has no key")
    if not size_seen:
        raise ValueError("section index entry has no size")
    return bytes(output)


def _section_directory(header_body: bytes) -> tuple[dict[int, tuple[int, int]], int, bool]:
    sections: dict[int, tuple[int, int]] = {}
    page_size = 0
    sectioned = False
    for header_field in fields(header_body):
        if header_field.number == 1 and header_field.wire == 0:
            page_size = int(header_field.value)
        elif header_field.number == 2 and header_field.wire == 0:
            sectioned = bool(header_field.value)
        elif header_field.number == 3 and header_field.wire == 2:
            key = None
            offset = 0
            size = None
            for entry_field in fields(bytes(header_field.value)):
                if entry_field.number == 1 and entry_field.wire == 0:
                    key = int(entry_field.value)
                elif entry_field.number == 2 and entry_field.wire == 2:
                    for value_field in fields(bytes(entry_field.value)):
                        if value_field.number == 1 and value_field.wire == 0:
                            offset = int(value_field.value)
                        elif value_field.number == 2 and value_field.wire == 0:
                            size = int(value_field.value)
            if key is None or size is None or key in sections:
                raise ValueError("invalid or duplicate section directory entry")
            sections[key] = (offset, size)
    return sections, page_size, sectioned


def rebuild_section_index(data: bytes) -> bytes:
    """Recompute paged-table offsets and lengths after row bytes change."""
    header, body = table_header(data)
    header_body = header[4:]
    old_sections, page_size, sectioned = _section_directory(header_body)
    if not sectioned:
        return data  # Non-sectioned tables have no directory to rebuild.
    if not old_sections:
        raise ValueError("sectioned table has no section directory")
    if page_size <= 0:
        raise ValueError("sectioned table has invalid page size")

    groups: dict[int, list[bytes]] = {}
    order: list[int] = []
    for top in fields(body):
        if top.number != 1 or top.wire != 2:
            raise ValueError("unexpected top-level table field")
        row_id, _, _ = row_info(bytes(top.value))
        page = row_id // page_size
        if page not in groups:
            groups[page] = []
            order.append(page)
        elif page != order[-1]:
            raise ValueError(f"rows for section {page} are not contiguous")
        groups[page].append(top.raw)

    directory: dict[int, tuple[int, int]] = {}
    offset = 0
    for page in order:
        chunk_size = sum(map(len, groups[page]))
        directory[page] = (offset, chunk_size)
        offset += chunk_size
    if set(directory) != set(old_sections):
        raise ValueError("section keys do not match table rows")

    out_header = bytearray()
    for header_field in fields(header_body):
        if header_field.number != 3 or header_field.wire != 2:
            out_header += header_field.raw
            continue
        entry = bytes(header_field.value)
        key = next((int(f.value) for f in fields(entry) if f.number == 1 and f.wire == 0), None)
        if key not in directory:
            raise ValueError("section index references a missing row group")
        out_header += length_field(3, _rewrite_section_entry(entry, *directory[key]))
    new_header = bytes(out_header)
    return len(new_header).to_bytes(4, "little") + new_header + body


def validate_section_index(data: bytes) -> int:
    """Check that every directory range parses to exactly its advertised ID page."""
    header, body = table_header(data)
    directory, page_size, sectioned = _section_directory(header[4:])
    if not sectioned:
        return 0
    if not directory:
        raise ValueError("sectioned table has no section directory")
    if page_size <= 0:
        raise ValueError("sectioned table has invalid page size")
    expected: dict[int, list[int]] = {}
    for top in fields(body):
        if top.number != 1 or top.wire != 2:
            raise ValueError("unexpected top-level table field")
        row_id, _, _ = row_info(bytes(top.value))
        expected.setdefault(row_id // page_size, []).append(row_id)
    if set(directory) != set(expected):
        raise ValueError("section directory keys do not match table rows")
    for page, (offset, size) in directory.items():
        if offset + size > len(body):
            raise ValueError(f"section {page} exceeds table body")
        chunk = body[offset:offset + size]
        actual_ids = []
        for top in fields(chunk):
            if top.number != 1 or top.wire != 2:
                raise ValueError(f"section {page} contains an invalid row wrapper")
            row_id, _, _ = row_info(bytes(top.value))
            if row_id // page_size != page:
                raise ValueError(f"section {page} contains row {row_id} from another page")
            actual_ids.append(row_id)
        if actual_ids != expected[page]:
            raise ValueError(f"section {page} range omits, duplicates, or reorders rows")
    return len(directory)


def row_info(raw: bytes) -> tuple[int, str, list[Field]]:
    fs = list(fields(raw))
    ids = [f for f in fs if f.number == 1 and f.wire == 0]
    texts = [f for f in fs if f.number == 2 and f.wire == 2]
    if len(ids) != 1 or len(texts) > 1:
        raise ValueError("language row must have one integer ID and at most one string field 2")
    text = bytes(texts[0].value).decode("utf-8", "strict") if texts else ""
    return int(ids[0].value), text, fs


def replace_table_text(data: bytes, replacements: dict[int, str]) -> tuple[bytes, int, int]:
    header, body = table_header(data)
    out = bytearray(header)
    seen: set[int] = set()
    changed = 0
    count = 0
    for top in fields(body):
        if top.number != 1 or top.wire != 2:
            raise ValueError("unexpected top-level table field")
        row_id, old_text, row_fields = row_info(bytes(top.value))
        if row_id in seen:
            raise ValueError(f"duplicate language row ID {row_id}")
        seen.add(row_id)
        count += 1
        new_text = replacements.get(row_id)
        if new_text is None or new_text == old_text:
            out += top.raw
            continue
        if not any(field.number == 2 and field.wire == 2 for field in row_fields):
            raise ValueError(f"replacement ID {row_id} has no text field")
        encoded = new_text.encode("utf-8", "strict")
        row_out = bytearray()
        replaced = False
        for field in row_fields:
            if field.number == 2 and field.wire == 2 and not replaced:
                row_out += length_field(2, encoded)
                replaced = True
            else:
                row_out += field.raw
        if not replaced:
            raise ValueError("row text field was lost")
        out += length_field(1, bytes(row_out))
        changed += 1
    unknown = set(replacements) - seen
    if unknown:
        raise ValueError(f"replacement IDs missing from table ({len(unknown)} IDs)")
    # `out` contains the original header followed by the rebuilt body.
    patched = rebuild_section_index(bytes(out))
    return patched, count, changed


def extract_texts(data: bytes) -> dict[int, str]:
    result = {}
    for row in table_rows(data):
        row_id, text, _ = row_info(bytes(row))
        if row_id in result:
            raise ValueError(f"duplicate language row ID {row_id}")
        result[row_id] = text
    return result


def validate_structure(original: bytes, patched: bytes) -> tuple[int, int]:
    """Require unchanged schema/rows except text field 2 and a valid rebuilt section index."""
    original_header, _ = table_header(original)
    patched_header, _ = table_header(patched)
    original_header_fields = list(fields(original_header[4:]))
    patched_header_fields = list(fields(patched_header[4:]))
    original_metadata = [f.raw for f in original_header_fields if f.number != 3]
    patched_metadata = [f.raw for f in patched_header_fields if f.number != 3]
    if original_metadata != patched_metadata:
        raise ValueError("non-index table header metadata changed")
    left = list(table_rows(original))
    right = list(table_rows(patched))
    if len(left) != len(right):
        raise ValueError("row count changed")
    changed = 0
    for before, after in zip(left, right):
        before_id, before_text, before_fields = row_info(bytes(before))
        after_id, after_text, after_fields = row_info(bytes(after))
        if before_id != after_id:
            raise ValueError("row ID or order changed")
        before_other = [f.raw for f in before_fields if f.number != 2]
        after_other = [f.raw for f in after_fields if f.number != 2]
        if before_other != after_other:
            raise ValueError(f"non-text columns changed for row {before_id}")
        changed += before_text != after_text
    validate_section_index(patched)
    return len(left), changed


def validate_subset_structure(original: bytes, candidate: bytes) -> tuple[int, int]:
    """Allow a client-normalized row subset and row-count header, but no other field edits."""
    original_header, _ = table_header(original)
    candidate_header, _ = table_header(candidate)
    original_header_fields = list(fields(original_header[4:]))
    candidate_header_fields = list(fields(candidate_header[4:]))
    original_count = [f for f in original_header_fields if f.number == 1 and f.wire == 0]
    candidate_count = [f for f in candidate_header_fields if f.number == 1 and f.wire == 0]
    if len(original_count) != 1 or len(candidate_count) != 1:
        raise ValueError("table row-count header is not recognized")
    original_metadata = [(f.number, f.wire, len(f.value) if isinstance(f.value, bytes) else None)
                         for f in original_header_fields if f.number != 1]
    candidate_metadata = [(f.number, f.wire, len(f.value) if isinstance(f.value, bytes) else None)
                          for f in candidate_header_fields if f.number != 1]
    if original_metadata != candidate_metadata:
        raise ValueError("non-count header fields changed")

    originals = {}
    original_order = []
    for raw in table_rows(original):
        row_id, _, row_fields = row_info(bytes(raw))
        if row_id in originals:
            raise ValueError(f"duplicate original row ID {row_id}")
        originals[row_id] = [f.raw for f in row_fields if f.number != 2]
        original_order.append(row_id)
    order = {row_id: index for index, row_id in enumerate(original_order)}
    last_index = -1
    count = 0
    for raw in table_rows(candidate):
        row_id, _, row_fields = row_info(bytes(raw))
        if row_id not in originals:
            raise ValueError(f"unknown row ID {row_id}")
        if order[row_id] <= last_index:
            raise ValueError("row order changed")
        last_index = order[row_id]
        if [f.raw for f in row_fields if f.number != 2] != originals[row_id]:
            raise ValueError(f"non-text columns changed for row {row_id}")
        count += 1
    if int(candidate_count[0].value) != count or count > len(originals):
        raise ValueError("row-count header does not match candidate rows")
    validate_section_index(candidate)
    return count, len(originals) - count
