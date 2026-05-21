package com.alexeygrigorev.phoneawsauth.ui.screens

import com.alexeygrigorev.phoneawsauth.net.GateClient
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainScreenTest {
    @Test
    fun gateActionsAreDisabledWhileBusy() {
        assertFalse(canRunGateAction(GateClient.Result.Closed, busy = true))
    }

    @Test
    fun gateActionsAreDisabledBeforeStatusLoads() {
        assertFalse(canRunGateAction(result = null, busy = false))
    }

    @Test
    fun gateActionsAreDisabledAfterStatusError() {
        assertFalse(canRunGateAction(GateClient.Result.Error("AccessDenied", "re-pair"), busy = false))
    }

    @Test
    fun gateActionsAreEnabledAfterSuccessfulClosedStatus() {
        assertTrue(canRunGateAction(GateClient.Result.Closed, busy = false))
    }

    @Test
    fun gateActionsAreEnabledAfterSuccessfulOpenStatus() {
        assertTrue(
            canRunGateAction(
                GateClient.Result.Open(
                    mode = "sandbox",
                    startedAt = 100,
                    expiresAt = 200,
                    note = "",
                ),
                busy = false,
            ),
        )
    }
}
