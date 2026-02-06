# Reaction class - control flow responses from hooks

class Reaction {
    [ReactionType]$Type
    [string]$Feedback   # For RetryWithFeedback
    [string]$Reason     # For Fail
    $Result             # For Finish

    Reaction([ReactionType]$type) {
        $this.Type = $type
    }

    static [Reaction] Continue() {
        return [Reaction]::new([ReactionType]::Continue)
    }

    static [Reaction] Retry() {
        return [Reaction]::new([ReactionType]::Retry)
    }

    static [Reaction] RetryWithFeedback([string]$feedback) {
        $r = [Reaction]::new([ReactionType]::RetryWithFeedback)
        $r.Feedback = $feedback
        return $r
    }

    static [Reaction] Fail([string]$reason) {
        $r = [Reaction]::new([ReactionType]::Fail)
        $r.Reason = $reason
        return $r
    }

    static [Reaction] Finish() {
        return [Reaction]::new([ReactionType]::Finish)
    }

    static [Reaction] Finish($result) {
        $r = [Reaction]::new([ReactionType]::Finish)
        $r.Result = $result
        return $r
    }
}
