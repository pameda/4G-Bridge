use framework "Foundation"
use scripting additions

on run argv
    if (count of argv) is not 1 then error "Invalid relay arguments" number 41000
    set operation to item 1 of argv
    if operation is not "check" and operation is not "send" then error "Invalid operation" number 41000
    set inputData to current application's NSFileHandle's fileHandleWithStandardInput()'s readDataToEndOfFile()
    if (inputData's |length|() as integer) > 1048576 then error "Invalid input size" number 41000
    set payload to current application's NSJSONSerialization's JSONObjectWithData:inputData options:0 |error|:(missing value)
    if payload is missing value then error "Invalid input" number 41000
    set targetValue to payload's objectForKey:"target"
    set bodyValue to payload's objectForKey:"body"
    if targetValue is missing value or bodyValue is missing value then error "Missing input" number 41000
    if not (targetValue's isKindOfClass:(current application's NSString)) then error "Invalid target" number 41000
    if not (bodyValue's isKindOfClass:(current application's NSString)) then error "Invalid body" number 41000
    set targetID to targetValue as text
    set messageText to bodyValue as text

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
