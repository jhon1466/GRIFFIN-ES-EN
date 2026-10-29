import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:archive/archive.dart';
import 'package:archive/archive_io.dart';
import 'package:crypto/crypto.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shizuku_api/shizuku_api.dart';

const game = 'com.Sunborn.SnqxExilium';
const configPath = 'LocalCache/Data/GameConfig.cfg';
const tablePath = 'LocalCache/Data/Table';
String bundledPatch(String locale) => 'patch/gf2-$locale-android-1.0.0.zip';
const patchVersion = '1.0.0';
void main() => runApp(const PatchApp());

class PatchApp extends StatelessWidget {
  const PatchApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'GRIFFIN ES/EN',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      fontFamily: 'MiSans',
      colorSchemeSeed: const Color(0xfff26c1f),
      scaffoldBackgroundColor: const Color(0xff0d1114),
    ),
    home: const PatchPage(),
  );
}

class PatchPage extends StatefulWidget {
  const PatchPage({super.key});
  @override
  State<PatchPage> createState() => _PatchPageState();
}

class _PatchPageState extends State<PatchPage>
    with SingleTickerProviderStateMixin {
  final api = ShizukuApi();
  final root = TextEditingController(
    text: '/storage/emulated/0/Android/data/$game/files',
  );
  bool busy = false, writable = false, installed = false;
  String locale = 'es';
  String? installedLocale;
  final patchedHashes = <String, String>{};
  String t(String es, String en) => locale == 'en' ? en : es;
  double progress = 0;
  int? shizukuUid;
  String status = 'Inicia Shizuku y pulsa Conectar. · Start Shizuku and tap Connect.';
  String client = '', tables = '';
  String patchLabel = '';
  String? patchTables;
  List<Map<String, String>> files = [];
  String? lastBackup, lastRoot;
  List<String> lastPaths = [];

  @override
  void initState() {
    super.initState();
    loadRestoreRecord();
  }

  String quote(String s) => "'${s.replaceAll("'", "'\"'\"'")}'";

  bool _validRoot(String path) =>
      path.startsWith('/') &&
      !path.contains(r'\') &&
      path.endsWith('/$game/files') &&
      !path.split('/').any((part) => part == '..' || part == '.');

  /// Only the language tables of the client may be written.
  bool safe(String p) =>
      RegExp(r'^LocalCache/Data/Table/LangPackageTable[A-Za-z]+Data\.bytes$')
          .hasMatch(p);

  void message(String s) {
    if (mounted) setState(() => status = s);
  }

  Future<String> command(String s) async => await api.runCommand(s) ?? '';

  Future<bool> shizukuReady() async {
    if (!(await api.pingBinder() ?? false)) {
      message(t('Shizuku no está iniciado. Ábrelo y arráncalo primero.', 'Shizuku is not running. Open it and start it first.'));
      return false;
    }
    var allowed = await api.checkPermission() ?? false;
    if (!allowed) allowed = await api.requestPermission() ?? false;
    if (!allowed) message(t('No se concedió el permiso de Shizuku.', 'Shizuku permission was not granted.'));
    return allowed;
  }

  Future<void> check() async {
    setState(() {
      busy = true;
      status = t('Comprobando Shizuku…', 'Checking Shizuku…');
    });
    try {
      if (!await shizukuReady()) return;
      final path = root.text.trim();
      if (!_validRoot(path)) {
        message(t('La ruta debe acabar en /$game/files.', 'The path must end in /$game/files.'));
        return;
      }
      final q = quote(path);
      final out = await command('''
uid=\$(id -u 2>/dev/null || echo -1)
echo "UID=\$uid"
if [ ! -f $q/$configPath ] || [ ! -f $q/$tablePath/LangPackageTableCnData.bytes ]; then echo NOT_FOUND; exit 0; fi
echo FOUND
echo "CLIENT=\$(sed -n 's/^CodeResVersion://p' $q/$configPath | head -n 1 | tr -d '\\r')"
echo "TABLES=\$(sed -n 's/^StcTableVersion://p' $q/$configPath | head -n 1 | tr -d '\\r')"
echo "MAIN=\$(sha256sum $q/$tablePath/LangPackageTableCnData.bytes | cut -d " " -f1)"
probe=$q/$tablePath/.gf2-es-probe-\$\$
if (umask 077; : > "\$probe") 2>/dev/null; then
  if rm -f "\$probe"; then echo WRITE_PROBE=1; else echo WRITE_PROBE=0; fi
else
  echo WRITE_PROBE=0
fi
''');
      shizukuUid = int.tryParse(
        RegExp(r'UID=(\d+)').firstMatch(out)?.group(1) ?? '',
      );
      if (!out.contains('FOUND') || out.contains('NOT_FOUND')) {
        writable = false;
        message(t(
          'No encuentro los datos del juego. Ábrelo una vez y deja que termine de descargar antes de instalar el parche.',
          'Game data not found. Open the game once and let it finish downloading before installing the patch.',
        ));
        return;
      }
      client = RegExp(r'CLIENT=([^\r\n]*)').firstMatch(out)?.group(1) ?? '';
      tables = RegExp(r'TABLES=([^\r\n]*)').firstMatch(out)?.group(1) ?? '';
      final main = RegExp(r'MAIN=([0-9a-f]{64})').firstMatch(out)?.group(1);
      writable = out.contains('WRITE_PROBE=1');
      await loadKnownHashes();
      if (files.isEmpty) await loadBundled();
      installedLocale = main == null ? null : patchedHashes[main];
      installed = installedLocale != null;
      message(
        !writable
            ? t('Se ven los datos del juego (UID ${shizukuUid ?? '?'}), pero no se pueden escribir. Usa Shizuku con ADB inalámbrico o root.',
                'The game data is visible (UID ${shizukuUid ?? '?'}) but not writable. Use Shizuku with wireless ADB or root.')
            : installed
            ? t('El juego ya está en ${installedLocale == 'en' ? 'inglés' : 'español'}. Puedes cambiar de idioma o volver al chino.',
                'The game is already in ${installedLocale == 'en' ? 'English' : 'Spanish'}. You can switch language or go back to Chinese.')
            : patchTables != null && patchTables != tables
            ? t('Conectado. Ojo: el parche es para las tablas $patchTables y el juego tiene $tables.',
                'Connected. Warning: the patch is for tables $patchTables and the game has $tables.')
            : t('Conectado. Pulsa Instalar.', 'Connected. Tap Install.'),
      );
    } catch (e) {
      message(t('Error de Shizuku: $e', 'Shizuku error: $e'));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  /// sha256 of the patched main table of every bundled language, to recognise
  /// a game that is already translated (and never back it up as "original").
  Future<void> loadKnownHashes() async {
    if (patchedHashes.isNotEmpty) return;
    for (final l in const ['es', 'en']) {
      final data = await rootBundle.load(bundledPatch(l));
      final archive = ZipDecoder().decodeBytes(data.buffer.asUint8List());
      final manifest = archive.files.firstWhere((f) => f.name == 'manifest.json');
      final json = jsonDecode(utf8.decode(manifest.content)) as Map<String, dynamic>;
      for (final f in json['files'] as List) {
        final e = f as Map<String, dynamic>;
        if ((e['path'] as String).endsWith('/LangPackageTableCnData.bytes')) {
          patchedHashes[e['sha256'] as String] = l;
        }
      }
    }
  }

  Future<void> loadBundled() async {
    final ext = await getExternalStorageDirectory();
    if (ext == null) throw Exception(t('No hay almacenamiento externo.', 'No external storage.'));
    final zip = File('${ext.path}/gf2_es_patch/bundled-$locale.zip');
    await zip.parent.create(recursive: true);
    final data = await rootBundle.load(bundledPatch(locale));
    await zip.writeAsBytes(data.buffer.asUint8List(), flush: true);
    await loadZip(zip.path, label: '${t('Incluido', 'Bundled')} · v$patchVersion');
  }

  Future<void> setLocale(String l) async {
    if (l == locale || busy) return;
    setState(() {
      locale = l;
      busy = true;
    });
    try {
      if (client.isNotEmpty) await loadBundled();
      message(t('Idioma: español.', 'Language: English.'));
    } catch (e) {
      message(t('No se pudo cargar: $e', 'Could not load: $e'));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> chooseZip() async {
    try {
      final pick = await FilePicker.pickFile(
        type: FileType.custom,
        allowedExtensions: const ['zip'],
      );
      if (pick?.path == null) return;
      setState(() => busy = true);
      await loadZip(pick!.path!, label: pick.name);
      message(t('Paquete $patchLabel verificado: ${files.length} tablas.', 'Package $patchLabel verified: ${files.length} tables.'));
    } catch (e) {
      message(t('No se pudo cargar: $e', 'Could not load: $e'));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> loadZip(String path, {required String label}) async {
    InputFileStream? zipInput;
    try {
      message(t('Validando el paquete…', 'Validating the package…'));
      zipInput = InputFileStream(path);
      final archive = ZipDecoder().decodeStream(zipInput);
      final manifests = archive.files
          .where((f) => f.name == 'manifest.json' && f.isFile)
          .toList();
      if (manifests.length != 1) {
        throw Exception('El ZIP necesita un manifest.json en la raíz.');
      }
      final json =
          jsonDecode(utf8.decode(manifests.single.content))
              as Map<String, dynamic>;
      if (!const ['gf2-lang-patch', 'gf2-es-patch'].contains(json['format']) ||
          json['schemaVersion'] != 1 ||
          json['gamePackage'] != game ||
          json['platform'] != 'android' ||
          json['files'] is! List ||
          (json['files'] as List).isEmpty) {
        throw Exception(t('Este paquete no es del parche de GF2 para Android.', 'This is not a GF2 Android patch package.'));
      }
      final ext = await getExternalStorageDirectory();
      if (ext == null) throw Exception('No hay almacenamiento externo.');
      final stage = Directory('${ext.path}/gf2_es_patch/staging');
      if (await stage.exists()) await stage.delete(recursive: true);
      await stage.create(recursive: true);
      final listed = <Map<String, String>>[];
      for (final raw in json['files'] as List) {
        final e = raw as Map<String, dynamic>;
        final dest = e['path'] as String, hash = e['sha256'] as String;
        final original = e['originalSha256'] as String?;
        if (!safe(dest) || !RegExp(r'^[0-9a-f]{64}$').hasMatch(hash)) {
          throw Exception('Ruta o hash inválido: $dest');
        }
        final payload = archive.files
            .where((f) => f.name == 'payload/$dest' && f.isFile)
            .toList();
        if (payload.length != 1) throw Exception('Falta payload/$dest');
        final output = File('${stage.path}/${dest.split('/').last}');
        final stream = OutputFileStream(output.path);
        try {
          payload.single.writeContent(stream);
        } finally {
          await stream.close();
        }
        final got = (await sha256.bind(output.openRead()).first).toString();
        if (got != hash) throw Exception('Hash incorrecto: $dest');
        listed.add({
          'path': dest,
          'hash': hash,
          'source': output.path,
          'originalHash': ?original,
        });
      }
      setState(() {
        files = listed;
        patchLabel = label;
        patchTables = json['stcTableVersion'] as String?;
      });
    } finally {
      await zipInput?.close();
    }
  }

  Future<void> install() async {
    if (!writable || files.isEmpty) return;
    setState(() {
      busy = true;
      progress = 0;
      status = t('Cerrando el juego y respaldando…', 'Closing the game and backing up…');
    });
    try {
      if (!await shizukuReady()) return;
      final ext = await getExternalStorageDirectory();
      if (ext == null) throw Exception('No hay almacenamiento externo.');
      final gameRoot = root.text.trim();
      // A backup already taken from the Chinese tables is kept: backing up a
      // Spanish table again would lose the way back.
      final backup =
          lastBackup ??
          '${ext.path}/gf2_es_patch/backups/${DateTime.now().millisecondsSinceEpoch}';
      // Hashes of every translated table we know (any language): those are
      // never backed up as if they were the Chinese originals.
      final patchedAll = {...patchedHashes.keys, ...files.map((f) => f['hash']!)};
      final script = StringBuffer('set -eu\nam force-stop $game || true\n');
      script.writeln('mkdir -p ${quote(backup)}');
      for (final f in files) {
        final dst = '$gameRoot/${f['path']!}';
        final save = '$backup/${f['path']!.split('/').last}';
        script.writeln(
          'test -f ${quote(dst)} || { echo "Falta ${f['path']}"; exit 1; }',
        );
        script.writeln(
          'if [ ! -f ${quote(save)} ]; then '
          'got=\$(sha256sum ${quote(dst)} | cut -d " " -f1); '
          'case "\$got" in ${patchedAll.map(quote).join('|')}) echo "__ALREADY__";; *) cp -p ${quote(dst)} ${quote(save)};; esac; fi',
        );
      }
      script.writeln('echo __BACKUP_OK__');
      final out = await command(script.toString());
      if (!out.contains('__BACKUP_OK__')) throw Exception(out);
      final paths = files.map((f) => f['path']!).toList();
      if (!out.contains('__ALREADY__') || lastBackup != null) {
        await saveRestoreRecord(backup, gameRoot, paths);
      }

      var done = 0;
      try {
        for (final f in files) {
          message(t('Instalando ${f['path']!.split('/').last}…', 'Installing ${f['path']!.split('/').last}…'));
          final dst = '$gameRoot/${f['path']!}';
          final tmp = '$dst.gf2-es-tmp';
          final hash = quote(f['hash']!);
          final out = await command('''
set -eu
cp ${quote(f['source']!)} ${quote(tmp)}
mode=\$(stat -c %a ${quote(dst)}); chmod "\$mode" ${quote(tmp)}
if [ "\$(id -u)" = 0 ]; then chown --reference=${quote(dst)} ${quote(tmp)}; fi
got=\$(sha256sum ${quote(tmp)} | cut -d " " -f1); [ "\$got" = $hash ]
mv -f ${quote(tmp)} ${quote(dst)}
got=\$(sha256sum ${quote(dst)} | cut -d " " -f1); [ "\$got" = $hash ]
echo __PATCH_OK__
''');
          if (!out.contains('__PATCH_OK__')) throw Exception(out);
          done++;
          setState(() => progress = done / files.length);
        }
      } catch (installError) {
        if (lastBackup != null) {
          final out = await command(restoreCommand(lastBackup!, gameRoot, paths));
          if (!out.contains('__RESTORE_OK__')) {
            throw Exception(
              t('Falló la instalación y no se pudo deshacer. El respaldo está en $lastBackup. $installError',
                'Install failed and could not be undone. The backup is in $lastBackup. $installError'),
            );
          }
        }
        throw Exception(
          t('Falló la instalación; se dejaron las tablas originales. $installError',
            'Install failed; the original tables were kept. $installError'),
        );
      }
      setState(() {
        installed = true;
        installedLocale = locale;
      });
      message(t('¡Listo! El juego está en español. Ábrelo normalmente.', 'Done! The game is in English. Open it as usual.'));
    } catch (e) {
      message(t('No se completó: $e', 'Not completed: $e'));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String restoreCommand(String backup, String gameRoot, List<String> paths) {
    final script = StringBuffer('set -eu\nam force-stop $game || true\n');
    for (final path in paths) {
      final save = '$backup/${path.split('/').last}';
      script.writeln(
        'test -f ${quote(save)} || { echo "Falta el respaldo de $path"; exit 1; }',
      );
    }
    for (final path in paths) {
      final dst = '$gameRoot/$path',
          save = '$backup/${path.split('/').last}',
          tmp = '$dst.gf2-es-restore';
      script.writeln(
        'cp -p ${quote(save)} ${quote(tmp)} && mv -f ${quote(tmp)} ${quote(dst)}',
      );
    }
    script.writeln('echo __RESTORE_OK__');
    return script.toString();
  }

  Future<void> restore() async {
    if (lastBackup == null || lastRoot == null || lastPaths.isEmpty) return;
    setState(() {
      busy = true;
      status = t('Restaurando el chino original…', 'Restoring the original Chinese…');
    });
    try {
      if (!await shizukuReady()) return;
      final out = await command(restoreCommand(lastBackup!, lastRoot!, lastPaths));
      if (!out.contains('__RESTORE_OK__')) throw Exception(out);
      final support = await getApplicationSupportDirectory();
      await File('${support.path}/last_patch.json').delete();
      await command('rm -rf ${quote(lastBackup!)}');
      setState(() {
        lastBackup = null;
        lastRoot = null;
        lastPaths = [];
        installed = false;
        installedLocale = null;
      });
      message(t('Se restauraron las tablas originales en chino.', 'The original Chinese tables were restored.'));
    } catch (e) {
      message(t('No se pudo restaurar: $e', 'Could not restore: $e'));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> saveRestoreRecord(
    String backup,
    String gameRoot,
    List<String> paths,
  ) async {
    lastBackup = backup;
    lastRoot = gameRoot;
    lastPaths = paths;
    final support = await getApplicationSupportDirectory();
    await File('${support.path}/last_patch.json').writeAsString(
      jsonEncode({'root': gameRoot, 'backup': backup, 'paths': paths}),
    );
  }

  Future<void> loadRestoreRecord() async {
    try {
      final support = await getApplicationSupportDirectory();
      final record = File('${support.path}/last_patch.json');
      if (!await record.exists()) return;
      final json =
          jsonDecode(await record.readAsString()) as Map<String, dynamic>;
      final savedRoot = json['root'] as String?;
      final savedBackup = json['backup'] as String?;
      final savedPaths = (json['paths'] as List).cast<String>();
      final ext = await getExternalStorageDirectory();
      if (savedRoot == null ||
          !_validRoot(savedRoot) ||
          savedBackup == null ||
          ext == null ||
          !savedBackup.startsWith('${ext.path}/gf2_es_patch/backups/') ||
          savedPaths.isEmpty ||
          savedPaths.any((path) => !safe(path))) {
        return;
      }
      if (!mounted) return;
      setState(() {
        lastRoot = savedRoot;
        lastBackup = savedBackup;
        lastPaths = savedPaths;
      });
    } catch (_) {}
  }

  // ── Diseño ────────────────────────────────────────────────────────────
  // Visual language of the client's update/login screen: its concept-art
  // backdrops (update_Bg1-4), the Exilium logo, the light-gray "提示" popup
  // with a header strip, and the dark buttons with the hexagonal confirm icon.
  static const _orange = Color(0xfff26c1f);
  static const _panel = Color(0xffe3e3e6);
  static const _header = Color(0xffc8c8cc);
  static const _ink = Color(0xff232a31);
  static const _inkSoft = Color(0xff5d646c);
  static const _button = Color(0xff1f272f);
  static const _line = Color(0xffb9bcc1);
  static const _bg = [
    'img/game/bg1.jpg',
    'img/game/bg2.jpg',
    'img/game/bg3.jpg',
    'img/game/bg4.jpg',
  ];

  late final AnimationController _pan = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 26),
  )..repeat(reverse: true);
  Timer? _bgTimer;
  int _bgIndex = 0;

  void _startBg() {
    _bgTimer ??= Timer.periodic(const Duration(seconds: 9), (_) {
      if (mounted) setState(() => _bgIndex = (_bgIndex + 1) % _bg.length);
    });
  }

  bool get _isError =>
      status.startsWith('No ') ||
      status.startsWith('Error') ||
      status.contains('Falló') ||
      status.contains('Ojo') ||
      status.contains('failed') ||
      status.contains('Warning') ||
      status.startsWith('Not ') ||
      status.startsWith('Could not') ||
      status.startsWith('Shizuku error') ||
      status.startsWith('Shizuku is not');

  @override
  Widget build(BuildContext context) {
    _startBg();
    final connected = client.isNotEmpty;
    final canInstall = !busy && writable && files.isNotEmpty;
    return Scaffold(
      body: Stack(
        fit: StackFit.expand,
        children: [
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 1800),
            child: AnimatedBuilder(
              key: ValueKey(_bgIndex),
              animation: _pan,
              builder: (_, child) => Transform.scale(
                scale: 1.15,
                child: Transform.translate(
                  offset: Offset(30 * (_pan.value - .5), 0),
                  child: child,
                ),
              ),
              child: Image.asset(
                _bg[_bgIndex],
                fit: BoxFit.cover,
                width: double.infinity,
                height: double.infinity,
              ),
            ),
          ),
          const DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [Color(0x880d1114), Color(0x220d1114), Color(0xdd0d1114)],
                stops: [0, .35, 1],
              ),
            ),
          ),
          SafeArea(
            child: Column(
              children: [
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 8),
                    children: [
                      _logo(),
                      const SizedBox(height: 20),
                      _popup(
                        title: t('Parche de idioma', 'Language patch'),
                        children: [
                          _languagePicker(),
                          const SizedBox(height: 18),
                          _sectionTitle('1', t('Conectar con Shizuku', 'Connect Shizuku')),
                          const SizedBox(height: 10),
                          _infoBox(
                            title: connected
                                ? t('Recursos $client · tablas $tables', 'Resources $client · tables $tables')
                                : t('Arranca Shizuku y concede el permiso', 'Start Shizuku and grant permission'),
                            badge: connected
                                ? (writable ? t('Escritura OK', 'Write OK') : t('Sin escritura', 'Read only'))
                                : null,
                            badgeOk: writable,
                            child: TextField(
                              controller: root,
                              style: const TextStyle(
                                fontSize: 11,
                                fontFamily: 'monospace',
                                color: _ink,
                              ),
                              decoration: const InputDecoration(
                                isDense: true,
                                border: InputBorder.none,
                                contentPadding: EdgeInsets.zero,
                              ),
                            ),
                          ),
                          const SizedBox(height: 10),
                          _button_(
                            connected ? t('Volver a comprobar', 'Check again') : t('Conectar', 'Connect'),
                            busy ? null : check,
                            icon: 'img/game/icon_language.png',
                          ),
                          const SizedBox(height: 20),
                          _sectionTitle('2', t('Paquete de traducción', 'Translation package')),
                          const SizedBox(height: 10),
                          _infoBox(
                            title: files.isNotEmpty
                                ? t('$patchLabel · ${files.length} tablas · tablas ${patchTables ?? '?'}', '$patchLabel · ${files.length} tables · tables ${patchTables ?? '?'}')
                                : t('Incluido en la app (se carga al conectar)', 'Bundled in the app (loaded when connecting)'),
                            badge: files.isNotEmpty ? t('Verificado', 'Verified') : null,
                            badgeOk: true,
                          ),
                          const SizedBox(height: 10),
                          _button_(
                            t('Usar otro ZIP', 'Use another ZIP'),
                            busy || !connected ? null : chooseZip,
                            light: true,
                          ),
                          const SizedBox(height: 20),
                          _sectionTitle('3', t('Instalar', 'Install')),
                          const SizedBox(height: 12),
                          _button_(
                            busy
                                ? t('Trabajando… ${(progress * 100).round()}%', 'Working… ${(progress * 100).round()}%')
                                : installedLocale == locale
                                ? t('Reinstalar en español', 'Reinstall in English')
                                : t('Instalar en español', 'Install in English'),
                            canInstall ? install : null,
                            icon: 'img/game/icon_confirm.png',
                            accent: true,
                            height: 58,
                            fontSize: 17,
                          ),
                          if (busy) ...[
                            const SizedBox(height: 10),
                            _progressBar(),
                          ],
                          if (lastPaths.isNotEmpty && !busy) ...[
                            const SizedBox(height: 10),
                            _button_(
                              t('Volver al chino', 'Back to Chinese'),
                              restore,
                              icon: 'img/game/icon_uninstall.png',
                              height: 44,
                              fontSize: 13,
                            ),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
                _statusBar(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _bgTimer?.cancel();
    _pan.dispose();
    root.dispose();
    super.dispose();
  }

  Widget _logo() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Image.asset('img/game/logo.png', width: 260),
      const SizedBox(height: 6),
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: const BoxDecoration(color: _orange),
        child: const Text(
          'ESPAÑOL · ENGLISH  ·  v$patchVersion',
          style: TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 2,
            color: Colors.white,
          ),
        ),
      ),
    ],
  );

  /// Two-way switch in the game's style: the active language is the dark tab.
  Widget _languagePicker() => Row(
    children: [
      for (final (code, label) in const [('es', 'Español'), ('en', 'English')])
        Expanded(
          child: GestureDetector(
            onTap: () => setLocale(code),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              height: 40,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: locale == code ? _ink : Colors.white.withValues(alpha: .55),
                border: Border.all(color: locale == code ? _orange : _line),
              ),
              child: Text(
                label,
                style: TextStyle(
                  color: locale == code ? _orange : _inkSoft,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
            ),
          ),
        ),
    ],
  );

  /// The client's popup: gray header strip with a centered title, light body,
  /// thin inner rules and a faint corner code like the game's "D-5718" marks.
  Widget _popup({required String title, required List<Widget> children}) =>
      Container(
        decoration: BoxDecoration(
          color: _panel,
          border: Border.all(color: Colors.white.withValues(alpha: .9), width: 2),
          boxShadow: const [
            BoxShadow(color: Color(0x99000000), blurRadius: 24, offset: Offset(0, 10)),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              margin: const EdgeInsets.all(6),
              padding: const EdgeInsets.symmetric(vertical: 10),
              color: _header,
              child: Text(
                title,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: _ink,
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              child: Container(height: 1, color: _line),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: children,
              ),
            ),
            const Padding(
              padding: EdgeInsets.fromLTRB(10, 0, 10, 6),
              child: Text(
                'GRIFFIN-ES-EN // LANG-PATCH',
                textAlign: TextAlign.right,
                style: TextStyle(fontSize: 8, letterSpacing: 2, color: _inkSoft),
              ),
            ),
          ],
        ),
      );

  Widget _sectionTitle(String number, String text) => Row(
    children: [
      Container(
        width: 22,
        height: 22,
        alignment: Alignment.center,
        color: _ink,
        child: Text(
          number,
          style: const TextStyle(
            color: _orange,
            fontSize: 12,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      const SizedBox(width: 8),
      Text(
        text,
        style: const TextStyle(
          color: _ink,
          fontSize: 14.5,
          fontWeight: FontWeight.w700,
        ),
      ),
      const SizedBox(width: 8),
      const Expanded(child: Divider(color: _line, height: 1)),
    ],
  );

  Widget _infoBox({
    required String title,
    String? badge,
    bool badgeOk = false,
    Widget? child,
  }) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .55),
      border: Border.all(color: _line),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                title,
                style: const TextStyle(
                  color: _inkSoft,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            if (badge != null)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                color: badgeOk ? _ink : const Color(0xffb8402a),
                child: Text(
                  badge,
                  style: TextStyle(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w700,
                    color: badgeOk ? _orange : Colors.white,
                  ),
                ),
              ),
          ],
        ),
        if (child != null) ...[const SizedBox(height: 6), child],
      ],
    ),
  );

  /// Dark game button with the hexagonal icon on its left edge (确认 style).
  Widget _button_(
    String label,
    VoidCallback? onTap, {
    String? icon,
    bool accent = false,
    bool light = false,
    double height = 48,
    double fontSize = 14,
  }) => Opacity(
    opacity: onTap == null ? .45 : 1,
    child: Material(
      color: light ? Colors.white.withValues(alpha: .7) : _button,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(3),
        side: BorderSide(
          color: accent ? _orange : (light ? _line : const Color(0xff3a4652)),
          width: accent ? 1.5 : 1,
        ),
      ),
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          height: height,
          child: Row(
            children: [
              if (icon != null)
                Padding(
                  padding: const EdgeInsets.only(left: 8),
                  child: Image.asset(icon, height: height * .62),
                )
              else
                const SizedBox(width: 12),
              Expanded(
                child: Text(
                  label,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: light ? _ink : Colors.white,
                    fontSize: fontSize,
                    fontWeight: FontWeight.w700,
                    letterSpacing: .6,
                  ),
                ),
              ),
              SizedBox(width: icon != null ? height * .62 + 8 : 12),
            ],
          ),
        ),
      ),
    ),
  );

  Widget _progressBar() => ClipRRect(
    child: LinearProgressIndicator(
      value: progress.clamp(0, 1),
      minHeight: 5,
      color: _orange,
      backgroundColor: _line,
    ),
  );

  Widget _statusBar() => Container(
    width: double.infinity,
    padding: const EdgeInsets.fromLTRB(22, 16, 22, 18),
    decoration: const BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [Color(0x000d1114), Color(0xe00d1114)],
      ),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(width: 4, height: 14, color: _orange),
            const SizedBox(width: 8),
            const Text(
              'GRIFFIN ES/EN',
              style: TextStyle(
                color: Colors.white70,
                fontSize: 11,
                fontWeight: FontWeight.w700,
                letterSpacing: 2,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          status,
          style: TextStyle(
            color: _isError ? const Color(0xffffc9b5) : Colors.white,
            fontSize: 15,
            height: 1.4,
            shadows: const [Shadow(blurRadius: 3)],
          ),
        ),
      ],
    ),
  );
}
