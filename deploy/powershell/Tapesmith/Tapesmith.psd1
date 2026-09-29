@{
    RootModule           = 'Tapesmith.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '0f9a84e8-6c9f-41e9-a7d5-209af3d1712f'
    Author               = 'tapesmith'
    CompanyName          = 'tapesmith'
    Copyright            = '(c) tapesmith.'
    Description          = 'Automatisierung des Phomemo P12 Labeldruckers aus der PowerShell-Konsole: drucken (auch aus der Pipeline), Vorschau, Status, Vorlagen und Warteschlange über die REST-API des Druckdienstes p12d.'
    PowerShellVersion    = '5.1'
    CompatiblePSEditions = @('Desktop', 'Core')
    FunctionsToExport    = @(
        'Connect-P12',
        'Disconnect-P12',
        'Get-P12Status',
        'Get-P12Template',
        'Send-P12Label',
        'New-P12Preview',
        'Get-P12Job',
        'Remove-P12Job'
    )
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags       = @('Tapesmith', 'Phomemo', 'Label', 'Drucker')
            ProjectUri = 'https://github.com/essendyx/tapesmith'
        }
    }
}
