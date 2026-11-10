package com.alexeygrigorev.phoneawsauth.net

import java.util.UUID
import kotlinx.coroutines.CancellationException
import aws.sdk.kotlin.runtime.auth.credentials.StaticCredentialsProvider
import aws.sdk.kotlin.services.dynamodb.DynamoDbClient
import aws.sdk.kotlin.services.dynamodb.model.AttributeValue
import aws.sdk.kotlin.services.dynamodb.model.DeleteItemRequest
import aws.sdk.kotlin.services.dynamodb.model.GetItemRequest
import aws.sdk.kotlin.services.dynamodb.model.PutItemRequest
import aws.smithy.kotlin.runtime.net.url.Url

/**
 * Reads/writes the DynamoDB gate rows that control the AWS access gate and
 * phone-approved resource requests (AWS, browser/desktop, SMS).
 *
 * Mirrors tools/phone_client.py.
 */
class GateClient(
    private val rowKey: String,
    private val table: String = "phone-aws-gate",
    private val awsRegion: String = "eu-west-1",
    private val accessKeyId: String,
    private val secretAccessKey: String,
    private val ddbEndpoint: String? = null,
) {

    data class ApprovalRequest(
        val id: String,
        val hostTokenHash: String,
        val requester: String,
        val resource: String,
        val scope: String,
        val reason: String,
        val ttlSeconds: Long,
        val requestedAt: Long,
        val expiresAt: Long,
    )

    sealed class Result {
        data class Open(
            val mode: String,
            val startedAt: Long,
            val expiresAt: Long,
            val note: String,
            val mainAccess: Boolean = false,
            val grantId: String = "",
        ) : Result()
        data object Closed : Result()
        data class Error(val type: String, val message: String) : Result()
    }

    private fun client(): DynamoDbClient = DynamoDbClient {
        region = awsRegion
        ddbEndpoint?.let { endpointUrl = Url.parse(it) }
        credentialsProvider = StaticCredentialsProvider {
            accessKeyId = this@GateClient.accessKeyId
            secretAccessKey = this@GateClient.secretAccessKey
        }
    }

    suspend fun start(mode: String, durationMinutes: Int, note: String = "", mainAccess: Boolean = false): Result {
        require(mode == "sandbox" || (mode == "main" && mainAccess)) {
            "Select AWS Sandbox, AWS Main, or both"
        }
        require(durationMinutes in 1..(24 * 60)) {
            "durationMinutes must be 1..1440, got $durationMinutes"
        }

        val now = System.currentTimeMillis() / 1000
        val expiresAt = now + durationMinutes * 60L
        val grantId = UUID.randomUUID().toString()

        return runCatching {
            val req = PutItemRequest {
                tableName = table
                item = mapOf(
                    "token_hash" to AttributeValue.S(rowKey),
                    "active" to AttributeValue.Bool(true),
                    "mode" to AttributeValue.S(mode),
                    "started_at" to AttributeValue.N(now.toString()),
                    "expires_at" to AttributeValue.N(expiresAt.toString()),
                    "note" to AttributeValue.S(note.take(200)),
                    "main_access" to AttributeValue.Bool(mainAccess),
                    "grant_id" to AttributeValue.S(grantId),
                )
            }
            client().use { it.putItem(req) }
            Result.Open(mode, now, expiresAt, note, mainAccess, grantId) as Result
        }.getOrElse {
            if (it is CancellationException) throw it
            Result.Error(it::class.simpleName ?: "Error", it.message ?: "")
        }
    }

    suspend fun stop(): Result {
        return runCatching {
            val req = DeleteItemRequest {
                tableName = table
                key = mapOf("token_hash" to AttributeValue.S(rowKey))
            }
            client().use { it.deleteItem(req) }
            Result.Closed as Result
        }.getOrElse {
            if (it is CancellationException) throw it
            Result.Error(it::class.simpleName ?: "Error", it.message ?: "")
        }
    }

    suspend fun status(): Result {
        return runCatching {
            val req = GetItemRequest {
                tableName = table
                consistentRead = true
                key = mapOf("token_hash" to AttributeValue.S(rowKey))
            }
            resultFromItem(client().use { it.getItem(req) }.item, System.currentTimeMillis() / 1000)
        }.getOrElse {
            if (it is CancellationException) throw it
            Result.Error(it::class.simpleName ?: "Error", it.message ?: "")
        }
    }

    suspend fun pendingRequests(includeGlobal: Boolean = true): List<ApprovalRequest> {
        val now = System.currentTimeMillis() / 1000
        return runCatching {
            client().use { ddb ->
                val seen = mutableSetOf<String>()
                val found = mutableListOf<ApprovalRequest>()
                val keys = buildList {
                    add("pending:$rowKey")
                    if (includeGlobal) add("pending:global")
                }
                for (pendingKey in keys) {
                    val pendingItem = ddb.getItem(GetItemRequest {
                        tableName = table
                        consistentRead = true
                        key = mapOf("token_hash" to AttributeValue.S(pendingKey))
                    }).item ?: continue
                    val list = (pendingItem["requests"] as? AttributeValue.L)?.value ?: emptyList()
                    for (entry in list) {
                        val map = (entry as? AttributeValue.M)?.value ?: continue
                        val reqId = (map["id"] as? AttributeValue.S)?.value ?: continue
                        if (reqId.isBlank() || !seen.add(reqId)) continue
                        val reqItem = ddb.getItem(GetItemRequest {
                            tableName = table
                            consistentRead = true
                            key = mapOf("token_hash" to AttributeValue.S("req:$reqId"))
                        }).item
                        parseApprovalRequest(reqItem, now, defaultHostHash = rowKey)?.let { found.add(it) }
                    }
                }
                found.sortedByDescending { it.requestedAt }
            }
        }.getOrElse {
            if (it is CancellationException) throw it
            emptyList()
        }
    }

    suspend fun decideRequest(requestId: String, approve: Boolean): Result {
        val now = System.currentTimeMillis() / 1000
        return runCatching {
            client().use { ddb ->
                val reqKey = "req:$requestId"
                val reqItem = ddb.getItem(GetItemRequest {
                    tableName = table
                    consistentRead = true
                    key = mapOf("token_hash" to AttributeValue.S(reqKey))
                }).item ?: return@use Result.Error("NotFound", "Request $requestId not found")

                val targetHash = ((reqItem["host_token_hash"] as? AttributeValue.S)?.value ?: rowKey).ifBlank { rowKey }
                val resource = ((reqItem["resource"] as? AttributeValue.S)?.value ?: "browser").ifBlank { "browser" }
                val scope = ((reqItem["scope"] as? AttributeValue.S)?.value ?: "default").ifBlank { "default" }
                val requester = (reqItem["requester"] as? AttributeValue.S)?.value ?: "agent"
                val reason = (reqItem["reason"] as? AttributeValue.S)?.value ?: ""
                val ttlSeconds = ((reqItem["ttl_s"] as? AttributeValue.N)?.value?.toLongOrNull() ?: 3600L).coerceIn(60L, 86400L)

                if (approve) {
                    val grantExpiresAt = now + ttlSeconds
                    val grantId = UUID.randomUUID().toString()
                    val grantAttributes = mapOf(
                        "active" to AttributeValue.Bool(true),
                        "resource" to AttributeValue.S(resource),
                        "scope" to AttributeValue.S(scope),
                        "requester" to AttributeValue.S(requester.take(120)),
                        "reason" to AttributeValue.S(reason.take(300)),
                        "started_at" to AttributeValue.N(now.toString()),
                        "expires_at" to AttributeValue.N(grantExpiresAt.toString()),
                        "grant_id" to AttributeValue.S(grantId),
                        "request_id" to AttributeValue.S(requestId),
                    )
                    for (gKey in listOf("grant:$targetHash:$resource:$scope", "grant:global:$resource:$scope")) {
                        ddb.putItem(PutItemRequest {
                            tableName = table
                            item = mapOf("token_hash" to AttributeValue.S(gKey)) + grantAttributes
                        })
                    }
                    if (resource == "aws-sandbox" || resource == "aws-main") {
                        ddb.putItem(PutItemRequest {
                            tableName = table
                            item = mapOf(
                                "token_hash" to AttributeValue.S(targetHash),
                                "active" to AttributeValue.Bool(true),
                                "mode" to AttributeValue.S("sandbox"),
                                "started_at" to AttributeValue.N(now.toString()),
                                "expires_at" to AttributeValue.N(grantExpiresAt.toString()),
                                "note" to AttributeValue.S(reason.take(200)),
                                "main_access" to AttributeValue.Bool(resource == "aws-main"),
                                "grant_id" to AttributeValue.S(grantId),
                                "requester" to AttributeValue.S(requester.take(120)),
                            )
                        })
                    }
                    val updatedReq = reqItem.toMutableMap().apply {
                        put("token_hash", AttributeValue.S(reqKey))
                        put("state", AttributeValue.S("approved"))
                        put("decided_at", AttributeValue.N(now.toString()))
                        put("grant_id", AttributeValue.S(grantId))
                        put("grant_expires_at", AttributeValue.N(grantExpiresAt.toString()))
                        put("expires_at", AttributeValue.N(grantExpiresAt.toString()))
                    }
                    ddb.putItem(PutItemRequest {
                        tableName = table
                        item = updatedReq
                    })
                    removePendingEntry(ddb, targetHash, requestId, now)
                    Result.Open("sandbox", now, grantExpiresAt, reason, resource == "aws-main", grantId)
                } else {
                    for (gKey in listOf("grant:$targetHash:$resource:$scope", "grant:global:$resource:$scope")) {
                        ddb.deleteItem(DeleteItemRequest {
                            tableName = table
                            key = mapOf("token_hash" to AttributeValue.S(gKey))
                        })
                    }
                    val updatedReq = reqItem.toMutableMap().apply {
                        put("token_hash", AttributeValue.S(reqKey))
                        put("state", AttributeValue.S("denied"))
                        put("decided_at", AttributeValue.N(now.toString()))
                    }
                    ddb.putItem(PutItemRequest {
                        tableName = table
                        item = updatedReq
                    })
                    removePendingEntry(ddb, targetHash, requestId, now)
                    Result.Closed
                }
            }
        }.getOrElse {
            if (it is CancellationException) throw it
            Result.Error(it::class.simpleName ?: "Error", it.message ?: "")
        }
    }

    private suspend fun removePendingEntry(ddb: DynamoDbClient, targetHash: String, requestId: String, now: Long) {
        for (pendingKey in listOf("pending:$targetHash", "pending:global")) {
            val pendingRow = ddb.getItem(GetItemRequest {
                tableName = table
                consistentRead = true
                key = mapOf("token_hash" to AttributeValue.S(pendingKey))
            }).item ?: continue
            val list = (pendingRow["requests"] as? AttributeValue.L)?.value ?: emptyList()
            val kept = list.filter { entry ->
                val map = (entry as? AttributeValue.M)?.value ?: return@filter false
                val id = (map["id"] as? AttributeValue.S)?.value ?: ""
                val exp = (map["expires_at"] as? AttributeValue.N)?.value?.toLongOrNull() ?: 0L
                id != requestId && exp > now
            }
            ddb.putItem(PutItemRequest {
                tableName = table
                this.item = mapOf(
                    "token_hash" to AttributeValue.S(pendingKey),
                    "requests" to AttributeValue.L(kept),
                    "expires_at" to AttributeValue.N((now + 86400L).toString()),
                )
            })
        }
    }
}

internal fun parseApprovalRequest(
    item: Map<String, AttributeValue>?,
    now: Long,
    defaultHostHash: String = "",
): GateClient.ApprovalRequest? {
    item ?: return null
    val state = (item["state"] as? AttributeValue.S)?.value ?: "pending"
    val expiresAt = (item["expires_at"] as? AttributeValue.N)?.value?.toLongOrNull() ?: 0L
    if (state != "pending" || expiresAt <= now) return null

    val id = (item["id"] as? AttributeValue.S)?.value ?: return null
    val requester = (item["requester"] as? AttributeValue.S)?.value ?: return null
    val resource = (item["resource"] as? AttributeValue.S)?.value ?: return null
    val scope = (item["scope"] as? AttributeValue.S)?.value ?: "default"
    val reason = (item["reason"] as? AttributeValue.S)?.value ?: ""
    val ttlSeconds = (item["ttl_s"] as? AttributeValue.N)?.value?.toLongOrNull() ?: 3600L
    val requestedAt = (item["requested_at"] as? AttributeValue.N)?.value?.toLongOrNull() ?: 0L
    val hostHash = ((item["host_token_hash"] as? AttributeValue.S)?.value ?: defaultHostHash).ifBlank { defaultHostHash }

    return GateClient.ApprovalRequest(
        id = id,
        hostTokenHash = hostHash,
        requester = requester,
        resource = resource,
        scope = scope,
        reason = reason,
        ttlSeconds = ttlSeconds,
        requestedAt = requestedAt,
        expiresAt = expiresAt,
    )
}

internal fun resultFromItem(item: Map<String, AttributeValue>?, now: Long): GateClient.Result {
    item ?: return GateClient.Result.Closed

    val active = (item["active"] as? AttributeValue.Bool)?.value ?: false
    val expiresAt = (item["expires_at"] as? AttributeValue.N)?.value?.toLongOrNull() ?: 0L
    if (!active || expiresAt <= now) {
        return GateClient.Result.Closed
    }

    return GateClient.Result.Open(
        mode = (item["mode"] as? AttributeValue.S)?.value ?: "",
        startedAt = (item["started_at"] as? AttributeValue.N)?.value?.toLongOrNull() ?: 0L,
        expiresAt = expiresAt,
        note = (item["note"] as? AttributeValue.S)?.value ?: "",
        mainAccess = (item["main_access"] as? AttributeValue.Bool)?.value ?: false,
        grantId = (item["grant_id"] as? AttributeValue.S)?.value ?: "",
    )
}
