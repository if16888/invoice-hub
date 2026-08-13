#define AppName "Invoice Hub"
#ifndef AppVersion
#define AppVersion "0.0.0"
#endif
#ifndef SourceDir
#define SourceDir "..\dist\InvoiceHub"
#endif
#ifndef OutputDir
#define OutputDir "..\dist"
#endif
#ifndef AppIdGuid
#define AppIdGuid "B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D"
#endif
#ifndef DefaultInstallDir
#define DefaultInstallDir "{localappdata}\Programs\InvoiceHub"
#endif

[Setup]
AppId={{B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Invoice Hub
DefaultDirName={#DefaultInstallDir}
DefaultGroupName=Invoice Hub
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=InvoiceHub-{#AppVersion}-win64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\InvoiceHub.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
; Legacy runtime export folders are removed only when migration left them empty.
Type: dirifempty; Name: "{app}\exports"
; A damaged previous uninstall registration may leave a renamed installer-owned
; uninstaller behind until this install is later removed.
Type: files; Name: "{app}\unins???.exe.invoicehub-orphan"
; When an older uninstall log was lost, the replacement log did not record the
; original app-directory creation. Remove it only when every owned file is gone.
Type: dirifempty; Name: "{app}"

[Icons]
Name: "{autoprograms}\Invoice Hub"; Filename: "{app}\InvoiceHub.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Invoice Hub"; Filename: "{app}\InvoiceHub.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\InvoiceHub.exe"; Description: "Launch Invoice Hub"; Flags: nowait postinstall skipifsilent

[Code]
const
  InvoiceHubUninstallKey =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppIdGuid}}_is1';

var
  BrokenRegisteredUninstaller: String;

function PathWithoutTrailingBackslash(const Value: String): String;
begin
  Result := RemoveBackslashUnlessRoot(Value);
end;

function RegisteredExecutable(const CommandLine: String): String;
var
  Value: String;
  ClosingQuote: Integer;
  ExeEnd: Integer;
begin
  Result := '';
  Value := Trim(CommandLine);
  if Value = '' then
    Exit;

  if Value[1] = '"' then
  begin
    Delete(Value, 1, 1);
    ClosingQuote := Pos('"', Value);
    if ClosingQuote > 1 then
      Result := Copy(Value, 1, ClosingQuote - 1);
    Exit;
  end;

  ExeEnd := Pos('.exe', Lowercase(Value));
  if ExeEnd > 0 then
    Result := Copy(Value, 1, ExeEnd + 3);
end;

function IsInnoUninstallerName(const FileName: String): Boolean;
var
  Name: String;
begin
  Name := Lowercase(FileName);
  Result :=
    (Length(Name) = 12) and
    (Copy(Name, 1, 5) = 'unins') and
    (Name[6] >= '0') and (Name[6] <= '9') and
    (Name[7] >= '0') and (Name[7] <= '9') and
    (Name[8] >= '0') and (Name[8] <= '9') and
    (Copy(Name, 9, 4) = '.exe');
end;

function FindAlternateUninstaller(
  const AppDirectory: String;
  const BrokenUninstaller: String): String;
var
  FindRec: TFindRec;
  Candidate: String;
begin
  Result := '';
  if FindFirst(AppDirectory + '\unins???.dat', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY = 0) then
        begin
          Candidate := AppDirectory + '\' +
            ChangeFileExt(FindRec.Name, '.exe');
          if FileExists(Candidate) and
             IsInnoUninstallerName(ExtractFileName(Candidate)) and
             (CompareText(Candidate, BrokenUninstaller) <> 0) and
             ((Result = '') or (CompareText(Candidate, Result) > 0)) then
            Result := Candidate;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function RepairBrokenUninstallRegistration: String;
var
  InstallLocation: String;
  UninstallCommand: String;
  UninstallerPath: String;
  AppDirectory: String;
  OrphanPath: String;
  AlternateUninstaller: String;
begin
  Result := '';
  if not RegQueryStringValue(
    HKEY_CURRENT_USER, InvoiceHubUninstallKey, 'InstallLocation',
    InstallLocation) then
    Exit;
  if not RegQueryStringValue(
    HKEY_CURRENT_USER, InvoiceHubUninstallKey, 'UninstallString',
    UninstallCommand) then
    Exit;

  InstallLocation := PathWithoutTrailingBackslash(InstallLocation);
  AppDirectory := InstallLocation;
  UninstallerPath := RegisteredExecutable(UninstallCommand);

  { Repair only the exact per-user Invoice Hub registration and only when its
    registered Inno uninstaller is directly inside the selected app directory. }
  if (CompareText(
       PathWithoutTrailingBackslash(ExtractFileDir(UninstallerPath)),
       AppDirectory) <> 0) or
     (not IsInnoUninstallerName(ExtractFileName(UninstallerPath))) then
    Exit;

  { A matching .dat makes this a valid uninstall registration. Native Inno
    upgrade/append behavior must remain untouched in that case. }
  if FileExists(ChangeFileExt(UninstallerPath, '.dat')) then
    Exit;

  Log('Detected an Invoice Hub uninstall registration without its matching log.');
  OrphanPath := UninstallerPath + '.invoicehub-orphan';
  if FileExists(OrphanPath) and (not DeleteFile(OrphanPath)) then
  begin
    Result := '检测到旧版卸载信息已损坏，且无法安全清理。请关闭 Invoice Hub 后重试安装。';
    Exit;
  end;
  if FileExists(UninstallerPath) and
     (not RenameFile(UninstallerPath, OrphanPath)) then
  begin
    Result := '检测到旧版卸载信息已损坏，且卸载程序正在使用。请关闭 Invoice Hub 后重试安装。';
    Exit;
  end;
  if FileExists(OrphanPath) and
     (not RenameFile(OrphanPath, UninstallerPath)) then
  begin
    Result := '检测到旧版卸载信息已损坏，且无法安全验证卸载程序。请重试安装。';
    Exit;
  end;

  AlternateUninstaller := FindAlternateUninstaller(
    AppDirectory, UninstallerPath);
  if AlternateUninstaller <> '' then
  begin
    Log('Found an alternate Inno uninstall log candidate.');
    { Point Setup at an existing candidate so Inno can verify its embedded
      AppId and append only when it belongs to this application. }
    if (not RegWriteStringValue(
      HKEY_CURRENT_USER, InvoiceHubUninstallKey, 'UninstallString',
      '"' + AlternateUninstaller + '"')) or
       (not RegWriteStringValue(
      HKEY_CURRENT_USER, InvoiceHubUninstallKey, 'QuietUninstallString',
      '"' + AlternateUninstaller + '" /SILENT')) then
    begin
      Result := '检测到旧版卸载信息已损坏，且无法修复卸载注册。请重试安装。';
      Exit;
    end;
  end
  else
  begin
    Log('No alternate Inno uninstall log candidate was found.');
    if not RegDeleteKeyIncludingSubkeys(
      HKEY_CURRENT_USER, InvoiceHubUninstallKey) then
    begin
      Result := '检测到旧版卸载信息已损坏，且无法修复卸载注册。请重试安装。';
      Exit;
    end;
  end;

  { Keep the orphan in place until Inno has selected/appended the current log.
    Removing it now could make Setup reuse its number and strand a valid
    alternate log. }
  BrokenRegisteredUninstaller := UninstallerPath;
  Log('Repaired the damaged Invoice Hub uninstall registration.');
end;

procedure RemoveBrokenRegisteredUninstaller;
var
  OrphanPath: String;
  MessagePath: String;
begin
  if BrokenRegisteredUninstaller = '' then
    Exit;

  OrphanPath := BrokenRegisteredUninstaller + '.invoicehub-orphan';
  if FileExists(BrokenRegisteredUninstaller) and
     (not DeleteFile(BrokenRegisteredUninstaller)) then
  begin
    if not RenameFile(BrokenRegisteredUninstaller, OrphanPath) then
      Log('Warning: could not remove the obsolete Invoice Hub uninstaller.');
  end;
  MessagePath := ChangeFileExt(BrokenRegisteredUninstaller, '.msg');
  if FileExists(MessagePath) then
    DeleteFile(MessagePath);
end;

function InitializeSetup: Boolean;
var
  RepairError: String;
begin
  RepairError := RepairBrokenUninstallRegistration;
  Result := RepairError = '';
  if not Result then
    SuppressibleMsgBox(RepairError, mbError, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RemoveBrokenRegisteredUninstaller;
end;
