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
#include "legacy\installer_ownership.issinc"
  InvoiceHubUninstallKey =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppIdGuid}}_is1';

var
  BrokenRegisteredUninstaller: String;
  LegacyPreservedData: String;
  LegacyUninstallAborted: Boolean;

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

function DirectoryHasEntries(const Directory: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if FindFirst(PathWithoutTrailingBackslash(Directory) + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Result := True;
          Break;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure RemoveEmptyDirectoryTree(const Directory: String);
var
  FindRec: TFindRec;
  ChildDirectory: String;
begin
  if not DirExists(Directory) then
    Exit;

  if FindFirst(PathWithoutTrailingBackslash(Directory) + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') and
           (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) and
           (FindRec.Attributes and FILE_ATTRIBUTE_REPARSE_POINT = 0) then
        begin
          ChildDirectory := PathWithoutTrailingBackslash(Directory) + '\' +
            FindRec.Name;
          RemoveEmptyDirectoryTree(ChildDirectory);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;

  { This procedure never deletes files. It only removes directories that are
    empty after native Inno uninstall processing, and it is called only for
    the installer-owned application tree. }
  if not DirectoryHasEntries(Directory) then
    RemoveDir(Directory);
end;

function RemoveBrokenUninstallRegistration: String;
var
  InstallLocation: String;
  UninstallCommand: String;
  UninstallerPath: String;
  AppDirectory: String;
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

  { Handle only the exact per-user Invoice Hub registration and only when its
    registered Inno uninstaller is directly inside the recorded app directory. }
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
  { Remove only the exact per-user ARP key. Do not rewrite either uninstall
    command and do not touch any uninsNNN.exe/.dat pair. Native Inno Setup must
    discover the AppId and choose a new or appended uninstall log itself. }
  if not RegDeleteKeyIncludingSubkeys(
    HKEY_CURRENT_USER, InvoiceHubUninstallKey) then
  begin
    Result := '检测到旧版卸载信息已损坏，且无法清理旧注册。请重试安装。';
    Exit;
  end;
  BrokenRegisteredUninstaller := UninstallerPath;
  Log('Removed the damaged Invoice Hub uninstall registration before native setup.');
end;

procedure RemoveBrokenRegisteredUninstaller;
begin
  if (BrokenRegisteredUninstaller = '') or
     (not FileExists(BrokenRegisteredUninstaller)) or
     FileExists(ChangeFileExt(BrokenRegisteredUninstaller, '.dat')) then
    Exit;

  { Native Setup owns the selected/new log. Remove only the previously
    registered installer-owned executable when it is still an unpaired stale
    file; never remove a valid alternate uninsNNN.exe/.dat pair. }
  if not DeleteFile(BrokenRegisteredUninstaller) then
    Log('Warning: could not remove the obsolete Invoice Hub uninstaller.');
end;

function IsUnsafeLegacyRelativePath(const Value: String): Boolean;
var
  Normalized: String;
  Remaining: String;
  Component: String;
  Separator: Integer;
begin
  Result := True;
  if Value = '' then
    Exit;

  Normalized := Value;
  StringChangeEx(Normalized, '/', '\', True);
  if (Normalized = '') or (Normalized[1] = '\') or
     ((Length(Normalized) >= 2) and (Normalized[2] = ':')) then
    Exit;

  Remaining := Normalized;
  while Remaining <> '' do
  begin
    Separator := Pos('\', Remaining);
    if Separator = 0 then
    begin
      Component := Remaining;
      Remaining := '';
    end
    else
    begin
      Component := Copy(Remaining, 1, Separator - 1);
      Delete(Remaining, 1, Separator);
    end;
    if (Component = '') or (Component = '.') or (Component = '..') then
      Exit;
  end;
  Result := False;
end;

function FindChildAttributes(
  const ParentDirectory, ChildName: String;
  var Attributes: Integer): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  Attributes := 0;
  if FindFirst(PathWithoutTrailingBackslash(ParentDirectory) + '\*', FindRec) then
  begin
    try
      repeat
        if CompareText(FindRec.Name, ChildName) = 0 then
        begin
          Attributes := FindRec.Attributes;
          Result := True;
          Break;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function LegacyPathHasReparsePoint(
  const AppDirectory, RelativePath: String): Boolean;
var
  ParentDirectory: String;
  Remaining: String;
  Component: String;
  Separator: Integer;
  Attributes: Integer;
begin
  Result := False;
  ParentDirectory := PathWithoutTrailingBackslash(AppDirectory);
  Remaining := RelativePath;
  StringChangeEx(Remaining, '/', '\', True);
  while Remaining <> '' do
  begin
    Separator := Pos('\', Remaining);
    if Separator = 0 then
    begin
      Component := Remaining;
      Remaining := '';
    end
    else
    begin
      Component := Copy(Remaining, 1, Separator - 1);
      Delete(Remaining, 1, Separator);
    end;

    if not FindChildAttributes(ParentDirectory, Component, Attributes) then
      Exit;
    if (Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0 then
    begin
      Result := True;
      Exit;
    end;
    ParentDirectory := PathWithoutTrailingBackslash(ParentDirectory) + '\' +
      Component;
  end;
end;

function BuildLegacyOwnedTarget(
  const RelativePath: String; var TargetPath: String): Boolean;
var
  Normalized: String;
  AppDirectory: String;
begin
  Result := False;
  TargetPath := '';
  if IsUnsafeLegacyRelativePath(RelativePath) then
  begin
    Log('Ignoring unsafe legacy ownership path.');
    Exit;
  end;

  Normalized := RelativePath;
  StringChangeEx(Normalized, '/', '\', True);
  AppDirectory := PathWithoutTrailingBackslash(ExpandConstant('{app}'));
  TargetPath := AppDirectory + '\' + Normalized;
  if CompareText(
       Copy(TargetPath, 1, Length(AppDirectory) + 1),
       AppDirectory + '\') <> 0 then
  begin
    TargetPath := '';
    Log('Ignoring legacy ownership path outside the application directory.');
    Exit;
  end;
  Result := True;
end;

function NextLegacyOwnershipRecord(
  var Remaining, RelativePath, ExpectedHash: String): Boolean;
var
  Line: String;
  LineEnd: Integer;
  Separator: Integer;
begin
  Result := False;
  RelativePath := '';
  ExpectedHash := '';
  if Remaining = '' then
    Exit;

  LineEnd := Pos(#13#10, Remaining);
  if LineEnd = 0 then
  begin
    Line := Remaining;
    Remaining := '';
  end
  else
  begin
    Line := Copy(Remaining, 1, LineEnd - 1);
    Delete(Remaining, 1, LineEnd + 1);
  end;

  Separator := Pos('|', Line);
  if Separator <= 1 then
    Exit;
  RelativePath := Copy(Line, 1, Separator - 1);
  ExpectedHash := Copy(Line, Separator + 1, Length(Line));
  Result := ExpectedHash <> '';
end;

function FindLegacyBackupPath(
  const TargetPath: String; var BackupPath: String): Boolean;
var
  Index: Integer;
  Candidate: String;
begin
  Result := False;
  BackupPath := TargetPath + '.invoicehub-preserved';
  if not FileExists(BackupPath) and not DirExists(BackupPath) then
  begin
    Result := True;
    Exit;
  end;

  for Index := 1 to 1000 do
  begin
    Candidate := TargetPath + '.invoicehub-preserved-' + IntToStr(Index);
    if not FileExists(Candidate) and not DirExists(Candidate) then
    begin
      BackupPath := Candidate;
      Result := True;
      Exit;
    end;
  end;
end;

function NextLegacyPreservedRecord(
  var Remaining, RelativePath, BackupPath: String): Boolean;
var
  Line: String;
  LineEnd: Integer;
  Separator: Integer;
begin
  Result := False;
  RelativePath := '';
  BackupPath := '';
  if Remaining = '' then
    Exit;

  LineEnd := Pos(#13#10, Remaining);
  if LineEnd = 0 then
  begin
    Line := Remaining;
    Remaining := '';
  end
  else
  begin
    Line := Copy(Remaining, 1, LineEnd - 1);
    Delete(Remaining, 1, LineEnd + 1);
  end;

  Separator := Pos('|', Line);
  if Separator <= 1 then
    Exit;
  RelativePath := Copy(Line, 1, Separator - 1);
  BackupPath := Copy(Line, Separator + 1, Length(Line));
  Result := BackupPath <> '';
end;

function RestoreLegacyFilesAfterNativeUninstall: Boolean; forward;

function FailLegacyProtection(
  const UserMessage: String; var ErrorText: String): Boolean;
begin
  ErrorText := UserMessage;
  { A previous record may already have been moved before this failure. Restore
    it before Abort so the application remains in its pre-uninstall state. }
  if not RestoreLegacyFilesAfterNativeUninstall then
    ErrorText := '无法安全恢复安装文件，卸载已取消。请不要重试并联系支持人员。';
  Result := False;
end;

function ProtectLegacyFilesBeforeNativeUninstall(
  var ErrorText: String): Boolean;
var
  Remaining: String;
  RelativePath: String;
  ExpectedHash: String;
  TargetPath: String;
  BackupPath: String;
  AppDirectory: String;
  ActualHash: String;
begin
  Result := False;
  ErrorText := '';
  AppDirectory := PathWithoutTrailingBackslash(ExpandConstant('{app}'));
  Remaining := LegacyOwnershipData;
  while NextLegacyOwnershipRecord(
    Remaining, RelativePath, ExpectedHash) do
  begin
    if not BuildLegacyOwnedTarget(RelativePath, TargetPath) then
      Continue;

    { A reparse point is an unsafe boundary, not a file to be moved. Check it
      before FileExists or hashing so no operation follows the redirected path. }
    if LegacyPathHasReparsePoint(AppDirectory, RelativePath) then
    begin
      Log('Refusing to touch a legacy path below a reparse point: ' +
        RelativePath);
      FailLegacyProtection(
        '检测到安装目录包含不安全的重解析路径，卸载已取消。请先移除该路径后重试。',
        ErrorText);
      Exit;
    end;
    if not FileExists(TargetPath) then
      Continue;

    ActualHash := GetSHA256OfFile(TargetPath);
    if CompareText(ActualHash, ExpectedHash) = 0 then
      Continue;

    if not FindLegacyBackupPath(TargetPath, BackupPath) then
    begin
      Log('Could not allocate a preservation name for legacy path: ' +
        RelativePath);
      FailLegacyProtection(
        '无法安全保护已修改的安装文件，卸载已取消。请关闭占用该文件的程序后重试。',
        ErrorText);
      Exit;
    end;
    if not RenameFile(TargetPath, BackupPath) then
    begin
      Log('Could not temporarily preserve legacy path before native uninstall: ' +
        RelativePath);
      FailLegacyProtection(
        '无法安全保护已修改的安装文件，卸载已取消。请关闭占用该文件的程序后重试。',
        ErrorText);
      Exit;
    end;
    LegacyPreservedData := LegacyPreservedData + RelativePath + '|' +
      BackupPath + #13#10;
    Log('Temporarily preserved legacy path before native uninstall: ' +
      RelativePath);
  end;
  Result := True;
end;

function RestoreLegacyFilesAfterNativeUninstall: Boolean;
var
  Remaining: String;
  RelativePath: String;
  BackupPath: String;
  TargetPath: String;
  AppDirectory: String;
begin
  Result := True;
  AppDirectory := PathWithoutTrailingBackslash(ExpandConstant('{app}'));
  Remaining := LegacyPreservedData;
  while NextLegacyPreservedRecord(
    Remaining, RelativePath, BackupPath) do
  begin
    if not BuildLegacyOwnedTarget(RelativePath, TargetPath) then
      Continue;
    if LegacyPathHasReparsePoint(AppDirectory, RelativePath) then
    begin
      Result := False;
      Log('Refusing to restore a legacy path below a reparse point: ' +
        RelativePath);
      Continue;
    end;
    if FileExists(BackupPath) then
    begin
      if FileExists(TargetPath) then
      begin
        Log('Preserving legacy backup because the original path was recreated: ' +
          RelativePath);
        Continue;
      end;
      if RenameFile(BackupPath, TargetPath) then
        Log('Restored preserved legacy path after native uninstall: ' +
          RelativePath)
      else
      begin
        Result := False;
        Log('Could not restore preserved legacy path after native uninstall: ' +
          RelativePath);
      end;
    end;
  end;
  LegacyPreservedData := '';
end;

procedure RemoveKnownLegacyOwnedFiles;
var
  Remaining: String;
  RelativePath: String;
  ExpectedHash: String;
  TargetPath: String;
  AppDirectory: String;
  ActualHash: String;
begin
  AppDirectory := PathWithoutTrailingBackslash(ExpandConstant('{app}'));
  Remaining := LegacyOwnershipData;
  while NextLegacyOwnershipRecord(
    Remaining, RelativePath, ExpectedHash) do
  begin
    if not BuildLegacyOwnedTarget(RelativePath, TargetPath) then
      Continue;
    if LegacyPathHasReparsePoint(AppDirectory, RelativePath) then
    begin
      Log('Preserving legacy path on a reparse point: ' + RelativePath);
      Continue;
    end;
    if not FileExists(TargetPath) then
      Continue;

    ActualHash := GetSHA256OfFile(TargetPath);
    if CompareText(ActualHash, ExpectedHash) <> 0 then
    begin
      Log('Preserving legacy path with an ownership hash mismatch: ' +
        RelativePath);
      Continue;
    end;
    if DeleteFile(TargetPath) then
      Log('Removed verified legacy installer-owned file: ' + RelativePath)
    else
      Log('Could not remove verified legacy installer-owned file: ' +
        RelativePath);
  end;
end;

function InitializeSetup: Boolean;
var
  RepairError: String;
begin
  RepairError := RemoveBrokenUninstallRegistration;
  Result := RepairError = '';
  if not Result then
    SuppressibleMsgBox(RepairError, mbError, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RemoveBrokenRegisteredUninstaller;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ProtectionError: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    LegacyPreservedData := '';
    LegacyUninstallAborted := False;
    if not ProtectLegacyFilesBeforeNativeUninstall(ProtectionError) then
    begin
      LegacyUninstallAborted := True;
      if ProtectionError = '' then
        ProtectionError := '无法安全保护安装文件，卸载已取消。请重试。';
      SuppressibleMsgBox(ProtectionError, mbError, MB_OK, IDOK);
      Abort;
    end;
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    if LegacyUninstallAborted then
      Exit;
    RestoreLegacyFilesAfterNativeUninstall;
    RemoveKnownLegacyOwnedFiles;
    RemoveEmptyDirectoryTree(ExpandConstant('{app}'));
  end;
end;
