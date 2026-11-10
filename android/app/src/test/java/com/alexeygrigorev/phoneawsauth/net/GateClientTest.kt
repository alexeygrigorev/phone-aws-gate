package com.alexeygrigorev.phoneawsauth.net

import aws.sdk.kotlin.services.dynamodb.model.AttributeValue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GateClientTest {
    @Test
    fun missingItemMapsToClosed() {
        assertEquals(GateClient.Result.Closed, resultFromItem(null, now = 100))
    }

    @Test
    fun inactiveItemMapsToClosed() {
        val item = openItem(active = false, expiresAt = 200)

        assertEquals(GateClient.Result.Closed, resultFromItem(item, now = 100))
    }

    @Test
    fun expiredItemMapsToClosed() {
        val item = openItem(expiresAt = 100)

        assertEquals(GateClient.Result.Closed, resultFromItem(item, now = 100))
        assertEquals(GateClient.Result.Closed, resultFromItem(item, now = 101))
    }

    @Test
    fun unexpiredActiveItemMapsToOpen() {
        val result = resultFromItem(openItem(expiresAt = 200), now = 100)

        assertTrue(result is GateClient.Result.Open)
        val open = result as GateClient.Result.Open
        assertEquals("sandbox", open.mode)
        assertEquals(50, open.startedAt)
        assertEquals(200, open.expiresAt)
        assertEquals("hello", open.note)
    }

    @Test
    fun malformedNumericFieldsMapToClosedOrZero() {
        val item = openItem(expiresAt = 200) + mapOf(
            "started_at" to AttributeValue.N("not-a-number"),
        )

        val result = resultFromItem(item, now = 100)

        assertTrue(result is GateClient.Result.Open)
        assertEquals(0, (result as GateClient.Result.Open).startedAt)
    }

    private fun openItem(
        active: Boolean = true,
        expiresAt: Long,
    ): Map<String, AttributeValue> = mapOf(
        "active" to AttributeValue.Bool(active),
        "mode" to AttributeValue.S("sandbox"),
        "started_at" to AttributeValue.N("50"),
        "expires_at" to AttributeValue.N(expiresAt.toString()),
        "note" to AttributeValue.S("hello"),
    )

    @Test
    fun mainAccessDefaultsFalseAndReadsChecked() {
        val item = mapOf(
            "active" to AttributeValue.Bool(true),
            "expires_at" to AttributeValue.N("4000000000"),
        )
        org.junit.Assert.assertFalse((resultFromItem(item, 100) as GateClient.Result.Open).mainAccess)
        val checked = item + mapOf(
            "main_access" to AttributeValue.Bool(true),
            "grant_id" to AttributeValue.S("grant-123"),
        )
        val result = resultFromItem(checked, 100) as GateClient.Result.Open
        org.junit.Assert.assertTrue(result.mainAccess)
        assertEquals("grant-123", result.grantId)
    }

    @Test
    fun parseApprovalRequestReadsPendingUnexpiredItem() {
        val item = mapOf(
            "id" to AttributeValue.S("req-1"),
            "host_token_hash" to AttributeValue.S("host-abc"),
            "requester" to AttributeValue.S("gate-hub-resilience-3"),
            "resource" to AttributeValue.S("browser"),
            "scope" to AttributeValue.S("desktop"),
            "reason" to AttributeValue.S("Run e2e browser smoke"),
            "ttl_s" to AttributeValue.N("1800"),
            "state" to AttributeValue.S("pending"),
            "requested_at" to AttributeValue.N("100"),
            "expires_at" to AttributeValue.N("500"),
        )
        val req = parseApprovalRequest(item, now = 200)
        assertNotNull(req)
        assertEquals("req-1", req!!.id)
        assertEquals("gate-hub-resilience-3", req.requester)
        assertEquals("browser", req.resource)
        assertEquals("desktop", req.scope)
        assertEquals("Run e2e browser smoke", req.reason)
        assertEquals(1800L, req.ttlSeconds)

        assertNull(parseApprovalRequest(item, now = 500))
        assertNull(parseApprovalRequest(item + mapOf("state" to AttributeValue.S("approved")), now = 200))
    }
}
