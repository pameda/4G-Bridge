-- Fixed synthetic self-test. No Messages/Keychain/USB/network access.
use framework "Foundation"
on run argv
    set inputData to current application's NSFileHandle's fileHandleWithStandardInput()'s readDataToEndOfFile()
    set payload to current application's NSJSONSerialization's JSONObjectWithData:inputData options:0 |error|:(missing value)
    if payload is missing value then error "Fixture input failed" number 41000
    set textValue to (payload's objectForKey:"body") as text
    if textValue is not "中文短信 📶" then error "Fixture Unicode mismatch" number 41000
    return "ACCEPTED"
end run
