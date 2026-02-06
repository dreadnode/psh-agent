function Select-WinningReaction {
    <#
    .SYNOPSIS
    Select the winning reaction from multiple hooks by priority
    Priority: Finish(5) > Fail(4) > Retry/RetryWithFeedback(3) > Continue(2)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [hashtable]$Reactions  # hookName -> Reaction
    )

    if ($Reactions.Count -eq 0) {
        return $null
    }

    $priorityMap = @{
        [ReactionType]::Finish            = 5
        [ReactionType]::Fail              = 4
        [ReactionType]::Retry             = 3
        [ReactionType]::RetryWithFeedback = 3
        [ReactionType]::Continue          = 2
    }

    $winner = $null
    $winnerPriority = -1

    foreach ($entry in $Reactions.GetEnumerator()) {
        $hookName = $entry.Key
        $reaction = $entry.Value
        $priority = $priorityMap[$reaction.Type]
        if ($null -eq $priority) { $priority = 1 }

        if ($priority -gt $winnerPriority) {
            $winner = @{
                HookName = $hookName
                Reaction = $reaction
            }
            $winnerPriority = $priority
        }
    }

    return $winner
}
