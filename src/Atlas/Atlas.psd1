@{
  RootModule        = 'Atlas.psm1'
  ModuleVersion     = '0.1.0'
  GUID              = '88823fe0-ed5b-4673-87d0-c2309efd3b12'
  Author            = 'rick'
  CompanyName       = ''
  Copyright         = ''
  Description       = 'Atlas PowerShell module (script-wrapped)'
  PowerShellVersion = '5.1'

  FunctionsToExport = @('Invoke-Atlas', 'Invoke-AtlasLiveFeedPublish', 'Invoke-AtlasRunAllAndPublish', 'Invoke-AtlasRunTodayAndExport')
  CmdletsToExport   = @()
  VariablesToExport = @()
  AliasesToExport   = @()
  PrivateData       = @{}
}
