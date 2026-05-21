package com.alexeygrigorev.phoneawsauth.net

import aws.sdk.kotlin.runtime.auth.credentials.StaticCredentialsProvider
import aws.sdk.kotlin.services.dynamodb.DynamoDbClient
import aws.sdk.kotlin.services.dynamodb.model.AttributeValue
import aws.sdk.kotlin.services.dynamodb.model.DeleteItemRequest
import aws.sdk.kotlin.services.dynamodb.model.GetItemRequest
import aws.sdk.kotlin.services.dynamodb.model.PutItemRequest
import aws.smithy.kotlin.runtime.net.url.Url

/**
 * Reads/writes the single DynamoDB gate row that controls the AWS access gate.
 *
 * Mirrors tools/phone_client.py. Three operations:
 *  - start(mode, durationMinutes): PutItem to open the gate
 *  - stop():                       DeleteItem to close it
 *  - status():                     GetItem to see current state
 *
 * The row is identified by [rowKey] (which on the server side is sha256(bearerToken));
 * the phone knows it from the pairing flow.
 *
 * For local dev set [ddbEndpoint] to "http://10.0.2.2:18000" (DDB Local).
 * For real AWS leave [ddbEndpoint] null and pass real IAM creds.
 */
class GateClient(
    private val rowKey: String,
    private val table: String = "phone-aws-gate",
    private val awsRegion: String = "eu-west-1",
    private val accessKeyId: String,
    private val secretAccessKey: String,
    private val ddbEndpoint: String? = null,
) {

    sealed class Result {
        data class Open(
            val mode: String,
            val startedAt: Long,
            val expiresAt: Long,
            val note: String,
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

    suspend fun start(mode: String, durationMinutes: Int, note: String = ""): Result {
        require(mode == "sandbox") {
            "mode must be 'sandbox', got $mode"
        }
        require(durationMinutes in 1..(24 * 60)) {
            "durationMinutes must be 1..1440, got $durationMinutes"
        }

        val now = System.currentTimeMillis() / 1000
        val expiresAt = now + durationMinutes * 60L

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
                )
            }
            client().use { it.putItem(req) }
            Result.Open(mode, now, expiresAt, note) as Result
        }.getOrElse { Result.Error(it::class.simpleName ?: "Error", it.message ?: "") }
    }

    suspend fun stop(): Result {
        return runCatching {
            val req = DeleteItemRequest {
                tableName = table
                key = mapOf("token_hash" to AttributeValue.S(rowKey))
            }
            client().use { it.deleteItem(req) }
            Result.Closed as Result
        }.getOrElse { Result.Error(it::class.simpleName ?: "Error", it.message ?: "") }
    }

    suspend fun status(): Result {
        return runCatching {
            val req = GetItemRequest {
                tableName = table
                key = mapOf("token_hash" to AttributeValue.S(rowKey))
            }
            val item = client().use { it.getItem(req) }.item
                ?: return@runCatching Result.Closed as Result

            val active = (item["active"] as? AttributeValue.Bool)?.value ?: false
            val expiresAt = (item["expires_at"] as? AttributeValue.N)?.value?.toLongOrNull() ?: 0L
            val now = System.currentTimeMillis() / 1000

            if (!active || expiresAt <= now) {
                Result.Closed
            } else {
                Result.Open(
                    mode = (item["mode"] as? AttributeValue.S)?.value ?: "",
                    startedAt = (item["started_at"] as? AttributeValue.N)?.value?.toLongOrNull() ?: 0L,
                    expiresAt = expiresAt,
                    note = (item["note"] as? AttributeValue.S)?.value ?: "",
                )
            }
        }.getOrElse { Result.Error(it::class.simpleName ?: "Error", it.message ?: "") }
    }
}
