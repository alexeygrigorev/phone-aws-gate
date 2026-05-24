package com.alexeygrigorev.phoneawsauth.updates

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseCheckerTest {
    @Test
    fun newerPatchVersionIsNewer() {
        assertTrue(isNewerVersion(current = "0.2.3", remote = "v0.2.4"))
    }

    @Test
    fun sameVersionIsNotNewer() {
        assertFalse(isNewerVersion(current = "0.2.3", remote = "v0.2.3"))
    }

    @Test
    fun olderRemoteVersionIsNotNewer() {
        assertFalse(isNewerVersion(current = "0.2.3", remote = "v0.2.2"))
    }

    @Test
    fun localSuffixIsIgnored() {
        assertTrue(isNewerVersion(current = "0.2.3-debug", remote = "v0.2.4"))
        assertFalse(isNewerVersion(current = "0.2.3-debug", remote = "v0.2.3"))
    }

    @Test
    fun newerMinorVersionIsNewer() {
        assertTrue(isNewerVersion(current = "0.2.9", remote = "v0.3.0"))
    }
}
