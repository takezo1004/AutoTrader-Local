; ============================================================
;  AutoTrader Local — インストーラー（Inno Setup）
;
;  配布仕様の正本＝リポルート DISTRIBUTION_MAP.md「ローカル版の配布仕様（D15）」。
;  ここに仕様を書き写さない。
;
;  ビルドは installer\build.ps1 が iscc に /D を渡して行う:
;    iscc /DMyAppVersion=x.y.z /DPayloadDir=<installer\payload> /DOutDir=<installer\output> N225Local.iss
; ============================================================

#ifndef MyAppVersion
  #error "MyAppVersion を /D で指定してください（build.ps1 が pyproject.toml から渡します）"
#endif
#ifndef PayloadDir
  #error "PayloadDir を /D で指定してください"
#endif
#ifndef OutDir
  #define OutDir "output"
#endif

#define MyAppName "AutoTrader Local"
#define MyAppExeName "AutoTrader-Local.exe"

[Setup]
AppId={{A7E3C1B4-9D52-4F18-8C6A-2B5D7E0F3A91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=takezo
; インストール先はユーザーフォルダ固定（D15）。置き場所を利用者に選ばせない。
DefaultDirName={%USERPROFILE}\AutoTraderLocal
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}
; 管理者権限を要求しない＝UAC を出さない（ユーザーフォルダにしか書かないため）
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=AutoTrader-Local-Setup-{#MyAppVersion}
SetupIconFile={#PayloadDir}\..\..\..\assets\localengine_dashboard.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; 稼働中は上書きさせない（ファイルが掴まれているため）
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作成する"; GroupDescription: "追加のタスク:"

[Files]
; ランチャー・ソース・lib・マニュアル（build.ps1 が payload に組み立てたもの）
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; ユーザーデータ。アンインストールでも消さない（設定・建玉・記録・戦略）
Name: "{app}\app\state"; Flags: uninsneveruninstall
Name: "{app}\data";      Flags: uninsneveruninstall
Name: "{app}\strategies"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\マニュアル"; Filename: "{app}\manual\manual.html"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent unchecked
Filename: "{app}\manual\manual.html"; Description: "マニュアルを開く"; Flags: shellexec nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\lib"
Type: filesandordirs; Name: "{app}\app\__pycache__"
