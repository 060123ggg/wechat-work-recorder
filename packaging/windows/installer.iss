#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#ifndef SourceDir
  #error "需要通过 /DSourceDir 指定 PyInstaller 输出目录"
#endif
#ifndef OutputDir
  #error "需要通过 /DOutputDir 指定安装包输出目录"
#endif

[Setup]
AppId={{C908D313-4D9C-4B4E-AE99-B9A97D956824}
AppName=微信记工助手
AppVersion={#AppVersion}
AppPublisher=wechat-work-recorder contributors
DefaultDirName={localappdata}\Programs\WechatWorkRecorder
DefaultGroupName=微信记工助手
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=WeChatWorkRecorder-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\WeChatWorkRecorder.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "创建桌面图标"; GroupDescription: "附加任务："; Flags: checkedonce

[Icons]
Name: "{userprograms}\微信记工助手"; Filename: "{app}\WeChatWorkRecorder.exe"
Name: "{userdesktop}\微信记工助手"; Filename: "{app}\WeChatWorkRecorder.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WeChatWorkRecorder.exe"; Description: "启动微信记工助手"; Flags: nowait postinstall skipifsilent
