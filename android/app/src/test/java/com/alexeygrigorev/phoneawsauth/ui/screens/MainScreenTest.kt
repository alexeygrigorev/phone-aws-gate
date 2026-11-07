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
}
