#requires -Version 7.2
[CmdletBinding()]
param([string]$MachineConfig='', [switch]$ValidateOnly)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$form=[Windows.Forms.Form]::new()
$form.Text='Steam Millennium 备份状态'
$form.Size=[Drawing.Size]::new(840,600)
$form.StartPosition='CenterScreen'
$bar=[Windows.Forms.FlowLayoutPanel]::new();$bar.Dock='Top';$bar.Height=44
$box=[Windows.Forms.TextBox]::new();$box.Multiline=$true;$box.ReadOnly=$true;$box.ScrollBars='Both';$box.Dock='Fill';$box.Font=[Drawing.Font]::new('Microsoft YaHei UI',10)
$note=[Windows.Forms.Label]::new();$note.Dock='Bottom';$note.Height=48;$note.Text='每周一 10:30（北京时间）自动备份，需要用户已登录。停止自动备份不会影响 Steam，也不会中断正在保存的快照。恢复操作必须先预检并退出 Steam。'
$form.Controls.Add($box);$form.Controls.Add($note);$form.Controls.Add($bar)
function Invoke-WindowCommand([string[]]$Arguments){
    $start=[Diagnostics.ProcessStartInfo]::new()
    $start.FileName=Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'
    $start.UseShellExecute=$false
    $start.CreateNoWindow=$true
    $start.RedirectStandardOutput=$true
    $start.RedirectStandardError=$true
    $start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
    $start.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
    foreach($argument in $Arguments){$start.ArgumentList.Add($argument)}
    $process=[Diagnostics.Process]::Start($start)
    try{
        $stdout=$process.StandardOutput.ReadToEndAsync()
        $stderr=$process.StandardError.ReadToEndAsync()
        while(-not $process.WaitForExit(100)){[Windows.Forms.Application]::DoEvents()}
        $text=$stdout.GetAwaiter().GetResult()
        $errorText=$stderr.GetAwaiter().GetResult()
        if($errorText){$text+="`r`n"+$errorText}
        return $text
    }finally{$process.Dispose()}
}
function Run-StatusCommand([string]$Mode){
    $bar.Enabled=$false
    $box.Text='正在核对快照、任务和独立副本……'
    [Windows.Forms.Application]::DoEvents()
    try{
        $a=@('-NoProfile','-NonInteractive','-File',(Join-Path $PSScriptRoot 'Invoke-MillenniumBackup.ps1'),'-Mode',$Mode,'-Json')
        if($MachineConfig){$a+=@('-MachineConfig',$MachineConfig)}
        $raw=Invoke-WindowCommand $a
        try{
            $status=$raw|ConvertFrom-Json -Depth 100
            $names=@{healthy='正常';complete='已完成';unchanged='无变化，已重新核验';needs_attention='需要处理';source_changed='源配置已变化';failed='失败';local_complete_replica_failed='本地成功，但独立副本失败'}
            $label=if($names.ContainsKey([string]$status.status)){$names[[string]$status.status]}else{[string]$status.status}
            $lines=[Collections.Generic.List[string]]::new()
            $lines.Add('备份状态：'+$label)
            if($status.last_success_utc){$lines.Add('最近成功：'+([datetimeoffset]$status.last_success_utc).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss zzz'))}
            if($status.verified_files){$lines.Add('已核验文件：'+$status.verified_files)}
            if($status.task){$lines.Add('自动任务：'+$status.task.state+'；已启用：'+$status.task.enabled);$lines.Add('最近返回码：'+$status.task.last_result);$lines.Add('下次运行：'+$status.task.next_run)}
            if($status.reason){$lines.Add('原因：'+$status.reason)}
            if($status.changes){$lines.Add('配置变化：'+@($status.changes).Count+' 项')}
            $lines.Add('');$lines.Add('详细核验记录：');$lines.Add($raw)
            $box.Text=$lines -join "`r`n"
        }catch{$box.Text=$raw}
    }finally{$bar.Enabled=$true}
}
foreach($label in @('刷新状态','立即备份','停止自动备份','启用自动备份','任务计划程序')){
    $button=[Windows.Forms.Button]::new();$button.Text=$label;$button.AutoSize=$true
    $button.Add_Click({
        try{
            switch($this.Text){
                '刷新状态'{Run-StatusCommand 'Status'}
                '立即备份'{Run-StatusCommand 'Snapshot'}
                '任务计划程序'{Start-Process taskschd.msc}
                default{
                    $mode=if($this.Text -eq '停止自动备份'){'Disable'}else{'Enable'}
                    $a=@('-NoProfile','-File',(Join-Path $PSScriptRoot 'Manage-MillenniumTask.ps1'),'-Mode',$mode)
                    if($MachineConfig){$a+=@('-MachineConfig',$MachineConfig)}
                    $box.Text=Invoke-WindowCommand $a
                }
            }
        }catch{$box.Text=$_.Exception.Message}
    })
    $bar.Controls.Add($button)
}
if($ValidateOnly){[pscustomobject]@{status='constructed';buttons=$bar.Controls.Count;title=$form.Text}|ConvertTo-Json;$form.Dispose();exit 0}
$form.Add_Shown({Run-StatusCommand 'Status'})
try{[void]$form.ShowDialog()}finally{$form.Dispose()}
