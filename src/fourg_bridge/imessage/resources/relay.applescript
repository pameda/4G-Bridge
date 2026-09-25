on run argv
    if (count of argv) is not 2 then error "Invalid relay arguments" number 41000
    set targetID to item 1 of argv
    set messageText to item 2 of argv

    tell application id "com.apple.MobileSMS"
        set availableServices to every service whose service type is iMessage and enabled is true and connection status is connected
        if (count of availableServices) is 0 then error "No connected iMessage service" number 41001
        set targetService to item 1 of availableServices
        try
            set targetParticipant to participant targetID of targetService
        on error
            error "iMessage target unavailable" number 41002
        end try
        send messageText to targetParticipant
    end tell
    return "ACCEPTED"
end run
