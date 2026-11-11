package com.alexeygrigorev.phoneawsauth.ui.screens

import com.alexeygrigorev.phoneawsauth.net.GateClient
import org.junit.Assert.assertEquals
import org.junit.Test

class MainScreenTest {
    @Test
    fun mainOnlyGrantDoesNotShowSandboxAsOpen() {
        val open = GateClient.Result.Open("main", 100, 200, "", mainAccess = true)
        assertEquals(AccessState.Closed, awsAccessState(open, CloudAccount.Sandbox, now = 199))
        assertEquals(AccessState.Open(200), awsAccessState(open, CloudAccount.Main, now = 199))
    }

    @Test
    fun sandboxGrantWithoutMainKeepsMainClosed() {
        val open = GateClient.Result.Open("sandbox", 100, 200, "")
        assertEquals(AccessState.Open(200), awsAccessState(open, CloudAccount.Sandbox, now = 199))
        assertEquals(AccessState.Closed, awsAccessState(open, CloudAccount.Main, now = 199))
    }

    @Test
    fun expiredGrantClosesBothAccounts() {
        val open = GateClient.Result.Open("sandbox", 100, 200, "", mainAccess = true)
        assertEquals(AccessState.Closed, awsAccessState(open, CloudAccount.Sandbox, now = 200))
        assertEquals(AccessState.Closed, awsAccessState(open, CloudAccount.Main, now = 200))
    }

    @Test
    fun failedStatusDoesNotPretendAccessIsClosed() {
        val error = GateClient.Result.Error("AccessDenied", "")
        assertEquals(AccessState.Unavailable, awsAccessState(error, CloudAccount.Sandbox, now = 200))
        assertEquals(AccessState.Unavailable, awsAccessState(error, CloudAccount.Main, now = 200))
    }

    @Test
    fun durationIndexUsesSavedOptionWhenValid() {
        assertEquals(2, durationIndexFor(listOf(15, 60, 240, 480), savedMinutes = 240))
    }

    @Test
    fun durationIndexFallsBackToOneHourWhenSavedOptionIsInvalid() {
        assertEquals(1, durationIndexFor(listOf(15, 60, 240, 480), savedMinutes = 999))
    }

    @Test
    fun formatDurationLabelFormatsHoursMinutesAndSeconds() {
        assertEquals("1h", formatDurationLabel(3600))
        assertEquals("30m", formatDurationLabel(1800))
        assertEquals("90s", formatDurationLabel(90))
    }

    private fun request(id: String) = GateClient.ApprovalRequest(
        id = id,
        hostTokenHash = "h",
        requester = "orin-vale",
        resource = "browser",
        scope = "desktop",
        reason = "verify",
        ttlSeconds = 900,
        requestedAt = 100,
        expiresAt = 1000,
    )

    @Test
    fun focusMatchesOnlyTheExactRequestFromTheNotification() {
        val target = request("abcd1234efgh")
        val other = request("999988887777")
        assert(focusesRequest(target, "abcd1234efgh"))
        assert(!focusesRequest(other, "abcd1234efgh"))
        assert(!focusesRequest(target, null))
    }

    @Test
    fun formatExpiresInShowsRoundedMinutes() {
        assertEquals("Expires: in 15m", formatExpiresIn(expiresAt = 1100, now = 200))
        assertEquals("Expires: in 1m", formatExpiresIn(expiresAt = 1060, now = 1000))
        assertEquals("Expires: in 0m", formatExpiresIn(expiresAt = 500, now = 1000))
    }
}
