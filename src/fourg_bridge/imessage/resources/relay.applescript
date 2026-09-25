on run argv
    if (count of argv) is not 3 then error "Invalid relay arguments" number 41000
    set operation to item 1 of argv
    if operation is not "check" and operation is not "send" then error "Invalid operation" number 41000
    set targetID to item 2 of argv
    set messageText to item 3 of argv

    tell application id "com.apple.MobileSMS"
        set availableServices to every account whose service type is iMessage and enabled is true and connection status is connected
        if (count of availableServices) is 0 then error "No connected iMessage service" number 41001
        set targetService to item 1 of availableServices
        try
            set targetParticipant to participant targetID of targetService
            set resolvedHandle to handle of targetParticipant
            if resolvedHandle is "" then error "Empty handle"
        on error
            error "iMessage target unavailable" number 41002
        end try
        if operation is "check" then return "CHECKED"
        log "BRIDGE_SEND_STARTED"
        send messageText to targetParticipant
    end tell
    return "ACCEPTED"
end run
