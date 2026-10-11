[Setup]
AppId=AgentVerse
AppName=AgentVerse
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\AgentVerse
DefaultGroupName=AgentVerse
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=agentverse-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\agentverse.exe
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\AgentVerse"; Filename: "{app}\agentverse.exe"
Name: "{autodesktop}\AgentVerse"; Filename: "{app}\agentverse.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\agentverse.exe"; Description: "Open AgentVerse"; Flags: nowait postinstall skipifsilent
[UninstallRun]
Filename: "{app}\agentverse.exe"; Parameters: "stop"; Flags: runhidden
