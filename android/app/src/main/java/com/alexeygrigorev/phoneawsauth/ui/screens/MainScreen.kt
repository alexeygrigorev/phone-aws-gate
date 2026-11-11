package com.alexeygrigorev.phoneawsauth.ui.screens

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationCompat
import com.alexeygrigorev.phoneawsauth.BuildConfig
import com.alexeygrigorev.phoneawsauth.MainActivity
import com.alexeygrigorev.phoneawsauth.auth.BiometricResult
import com.alexeygrigorev.phoneawsauth.auth.findFragmentActivity
import com.alexeygrigorev.phoneawsauth.auth.requireBiometric
import com.alexeygrigorev.phoneawsauth.net.GateClient
import com.alexeygrigorev.phoneawsauth.net.GcpGateClient
import com.alexeygrigorev.phoneawsauth.net.LocalDev
import com.alexeygrigorev.phoneawsauth.settings.PairedSettings
import com.alexeygrigorev.phoneawsauth.updates.ReleaseChecker
import com.alexeygrigorev.phoneawsauth.updates.ReleaseInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Locale

internal enum class CloudAccount(val label: String) {
    Sandbox("AWS Sandbox"),
    Main("AWS Main"),
    GoogleCloud("Google Cloud"),
}

private data class HostGate(
    val id: String,
    val name: String,
    val aws: GateClient,
    val gcp: GcpGateClient? = null,
)

internal sealed interface AccessState {
    data object Checking : AccessState
    data object Closed : AccessState
    data object Unavailable : AccessState
    data object NotPaired : AccessState
    data class Open(val expiresAt: Long) : AccessState
}

private data class HostStatus(
    val aws: GateClient.Result,
    val gcp: GcpGateClient.Result?,
    val pending: List<GateClient.ApprovalRequest> = emptyList(),
)

internal fun awsAccessState(result: GateClient.Result?, account: CloudAccount, now: Long): AccessState {
    return when (result) {
        null -> AccessState.Checking
        is GateClient.Result.Error -> AccessState.Unavailable
        GateClient.Result.Closed -> AccessState.Closed
        is GateClient.Result.Open -> {
            val allowed = when (account) {
                CloudAccount.Sandbox -> result.mode == "sandbox"
                CloudAccount.Main -> result.mainAccess && (result.mode == "main" || result.mode == "sandbox")
                CloudAccount.GoogleCloud -> false
            }
            if (allowed && result.expiresAt > now) AccessState.Open(result.expiresAt) else AccessState.Closed
        }
    }
}

private fun accessState(host: HostGate, status: HostStatus?, account: CloudAccount, now: Long): AccessState {
    if (account != CloudAccount.GoogleCloud) return awsAccessState(status?.aws, account, now)
    if (host.gcp == null) return AccessState.NotPaired
    return when (val result = status?.gcp) {
        null -> AccessState.Checking
        is GcpGateClient.Result.Error -> AccessState.Unavailable
        is GcpGateClient.Result.Grant ->
            if (result.expiresAt > now) AccessState.Open(result.expiresAt) else AccessState.Closed
    }
}

private suspend fun readStatus(host: HostGate, includePending: Boolean = true): HostStatus = coroutineScope {
    val aws = async(Dispatchers.IO) { host.aws.status() }
    val gcp = async(Dispatchers.IO) { host.gcp?.status() }
    val pending = async(Dispatchers.IO) { if (includePending) host.aws.pendingRequests(includeGlobal = true) else emptyList() }
    HostStatus(aws.await(), gcp.await(), pending.await())
}

private suspend fun setAccess(host: HostGate, accounts: Set<CloudAccount>, durationMinutes: Int): String? =
    coroutineScope {
        val aws = async(Dispatchers.IO) {
            val sandbox = CloudAccount.Sandbox in accounts
            val main = CloudAccount.Main in accounts
            if (sandbox || main) {
                host.aws.start(if (sandbox) "sandbox" else "main", durationMinutes, mainAccess = main)
            } else {
                host.aws.stop()
            }
        }
        val gcp = async(Dispatchers.IO) {
            host.gcp?.let {
                if (CloudAccount.GoogleCloud in accounts) it.start(durationMinutes) else it.stop()
            }
        }
        val awsResult = aws.await()
        val gcpResult = gcp.await()
        buildList {
            if (awsResult is GateClient.Result.Error) add("AWS: ${awsResult.type}")
            if (gcpResult is GcpGateClient.Result.Error) add("Google Cloud: ${gcpResult.message}")
        }.joinToString("\n").ifEmpty { null }
    }

@Composable
fun MainScreen(onPair: () -> Unit, pairVersion: Int, focusRequestId: String? = null) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val settings = remember { PairedSettings(context) }
    val activity = remember(context) { context.findFragmentActivity() }
    val preferences = remember(context) { context.getSharedPreferences("phone-aws-ui", 0) }
    var updateInfo by remember { mutableStateOf<ReleaseInfo?>(null) }
    var pairedHosts by remember(pairVersion) { mutableStateOf(settings.hosts()) }
    var selectedKey by remember(pairVersion) { mutableStateOf(settings.load()?.rowKey) }
    var devOverride by remember(pairVersion) { mutableStateOf(false) }
    val hosts = remember(pairedHosts, devOverride) {
        pairedHosts.map { host ->
            HostGate(
                id = host.rowKey,
                name = host.name,
                aws = GateClient(host.rowKey, host.table, host.region, host.accessKeyId, host.secretAccessKey, host.ddbEndpoint),
                gcp = host.gcp?.let { GcpGateClient(host.rowKey, it) },
            )
        }.ifEmpty {
            if (devOverride) listOf(HostGate(LocalDev.ROW_KEY, "Local emulator", LocalDev.client())) else emptyList()
        }
    }
    val statuses = remember(hosts) { mutableStateMapOf<String, HostStatus>() }
    val notifiedRequestIds = remember { mutableStateMapOf<String, Boolean>() }
    val selected = hosts.firstOrNull { it.id == selectedKey } ?: hosts.firstOrNull()
    var busy by remember { mutableStateOf(false) }
    var feedback by remember(selected?.id) { mutableStateOf<String?>(null) }
    var edits by remember(selected?.id) { mutableStateOf<Set<CloudAccount>?>(null) }
    var now by remember { mutableLongStateOf(epochSeconds()) }
    val durationOptions = listOf(15, 60, 240, 480)
    var durationIdx by remember {
        mutableIntStateOf(durationIndexFor(durationOptions, preferences.getInt(KEY_DEFAULT_DURATION_MINUTES, 60)))
    }

    suspend fun refresh() = coroutineScope {
        hosts.forEachIndexed { idx, host ->
            launch {
                val st = readStatus(host, includePending = idx == 0 || host.id == selected?.id)
                statuses[host.id] = st
                st.pending.forEach { req ->
                    if (notifiedRequestIds.put(req.id, true) == null) {
                        notifyPendingRequest(context, req)
                    }
                }
            }
        }
    }

    LaunchedEffect(Unit) {
        updateInfo = ReleaseChecker().check(currentVersionName(context))
        while (true) {
            now = epochSeconds()
            delay(1000)
        }
    }
    LaunchedEffect(hosts) {
        while (hosts.isNotEmpty()) {
            refresh()
            delay(5000)
        }
    }

    val debugSkipBiometric = BuildConfig.GATE_E2E &&
        context.getSharedPreferences("phone-aws-debug", 0).getBoolean("skip_biometric", false)

    fun apply(host: HostGate, accounts: Set<CloudAccount>, duration: Int) {
        busy = true
        feedback = null
        scope.launch {
            try {
                if (accounts.isNotEmpty() && !devOverride && !debugSkipBiometric) {
                    val authentication = activity?.let {
                        requireBiometric(it, "Apply access for ${host.name}", "Cloud Gate")
                    }
                    feedback = when (authentication) {
                        BiometricResult.Authenticated -> null
                        BiometricResult.UserCancelled -> "Biometric cancelled"
                        BiometricResult.NotAvailable -> "No biometric enrolled"
                        is BiometricResult.Failed -> authentication.reason
                        null -> "Biometric prompt is unavailable"
                    }
                    if (authentication != BiometricResult.Authenticated) return@launch
                }
                val error = setAccess(host, accounts, duration)
                statuses[host.id] = readStatus(host)
                now = epochSeconds()
                edits = null
                feedback = error?.let { "Some changes could not be confirmed:\n$it" }
            } finally {
                busy = false
            }
        }
    }

    fun decide(host: HostGate, req: GateClient.ApprovalRequest, approve: Boolean) {
        busy = true
        feedback = null
        scope.launch {
            try {
                if (approve && !devOverride && !debugSkipBiometric) {
                    val authentication = activity?.let {
                        requireBiometric(it, "Approve ${req.resource} for ${req.requester}", "Cloud Gate")
                    }
                    feedback = when (authentication) {
                        BiometricResult.Authenticated -> null
                        BiometricResult.UserCancelled -> "Biometric cancelled"
                        BiometricResult.NotAvailable -> "No biometric enrolled"
                        is BiometricResult.Failed -> authentication.reason
                        null -> "Biometric prompt is unavailable"
                    }
                    if (authentication != BiometricResult.Authenticated) return@launch
                }
                val res = kotlinx.coroutines.withContext(Dispatchers.IO) {
                    host.aws.decideRequest(req.id, approve = approve)
                }
                if (res is GateClient.Result.Error) {
                    feedback = "${res.type}: ${res.message}"
                }
                refresh()
                now = epochSeconds()
            } finally {
                busy = false
            }
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Cloud Gate", style = MaterialTheme.typography.headlineMedium)
        UpdateBanner(updateInfo = updateInfo, onUpdate = { openUrl(context, it.apkUrl) })
        if (selected == null) {
            Text("Register a computer to see and manage its cloud access.")
            Button(onClick = onPair) { Text("Register computer") }
            if (BuildConfig.GATE_E2E) {
                OutlinedButton(onClick = { devOverride = true }) { Text("Use local emulator") }
            }
        } else {
            val allPending = statuses.values
                .flatMap { it.pending }
                .distinctBy { it.id }
                .filter { it.expiresAt > now }
            if (allPending.isNotEmpty()) {
                Text("Pending approval requests", style = MaterialTheme.typography.titleMedium)
                allPending.forEach { req ->
                    PendingRequestCard(
                        req = req,
                        busy = busy,
                        focused = focusesRequest(req, focusRequestId),
                        onApprove = { decide(selected, req, approve = true) },
                        onDeny = { decide(selected, req, approve = false) },
                    )
                }
                HorizontalDivider()
            }
            Text("Access by computer", style = MaterialTheme.typography.titleMedium)
            AccessMatrix(hosts, selected, statuses, now, enabled = !busy) { host ->
                settings.select(host.id)
                selectedKey = host.id
            }
            HorizontalDivider()
            val status = statuses[selected.id]
            val openAccounts = CloudAccount.entries.filter { accessState(selected, status, it, now) is AccessState.Open }.toSet()
            val accounts = edits ?: openAccounts.ifEmpty { setOf(CloudAccount.Sandbox) }
            val durationMinutes = durationOptions[durationIdx]
            val durationLabel = if (durationMinutes < 60) "${durationMinutes}m" else "${durationMinutes / 60}h"
            val canApply = !busy && status != null && accounts.isNotEmpty()
            Text("Manage ${selected.name}", style = MaterialTheme.typography.titleLarge)
            Text("Apply sets access to the accounts you select.", style = MaterialTheme.typography.bodySmall)
            Column {
                CloudAccount.entries.forEach { account ->
                    val paired = account != CloudAccount.GoogleCloud || selected.gcp != null
                    AccountChoice(
                        account = account,
                        checked = account in accounts,
                        enabled = !busy && paired,
                        paired = paired,
                    ) { checked ->
                        edits = if (checked) accounts + account else accounts - account
                    }
                }
            }
            Text("Close automatically after", style = MaterialTheme.typography.labelLarge)
            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                durationOptions.forEachIndexed { i, minutes ->
                    SegmentedButton(
                        shape = SegmentedButtonDefaults.itemShape(i, durationOptions.size),
                        selected = i == durationIdx,
                        enabled = !busy,
                        onClick = {
                            durationIdx = i
                            preferences.edit().putInt(KEY_DEFAULT_DURATION_MINUTES, minutes).apply()
                        },
                    ) { Text(if (minutes < 60) "${minutes}m" else "${minutes / 60}h") }
                }
            }
            feedback?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(enabled = canApply, onClick = { apply(selected, accounts, durationMinutes) }) {
                    Text("Apply ($durationLabel)")
                }
                OutlinedButton(enabled = !busy && status != null, onClick = { apply(selected, emptySet(), durationMinutes) }) {
                    Text("Stop all")
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(enabled = !busy, onClick = {
                    busy = true
                    scope.launch {
                        try {
                            refresh()
                            now = epochSeconds()
                        } finally {
                            busy = false
                        }
                    }
                }) { Text("Refresh") }
                TextButton(enabled = !busy, onClick = onPair) { Text("Register computer") }
            }
            TextButton(enabled = !busy, onClick = {
                if (devOverride) {
                    devOverride = false
                } else {
                    settings.remove(selected.id)
                    pairedHosts = settings.hosts()
                    selectedKey = settings.load()?.rowKey
                }
            }) { Text("Forget ${selected.name}") }
        }
    }
}

@Composable
private fun PendingRequestCard(
    req: GateClient.ApprovalRequest,
    busy: Boolean,
    focused: Boolean = false,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "Approval request ${req.id}" }
            .then(
                if (focused) Modifier.border(3.dp, MaterialTheme.colorScheme.primary, MaterialTheme.shapes.medium)
                else Modifier
            ),
        color = MaterialTheme.colorScheme.secondaryContainer,
        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text("Who asks: ${req.requester}", style = MaterialTheme.typography.titleSmall)
            Text("Resource: ${req.resource} (${req.scope})", style = MaterialTheme.typography.bodyMedium)
            Text("Why: ${req.reason}", style = MaterialTheme.typography.bodyMedium)
            Text("Duration: ${formatDurationLabel(req.ttlSeconds)}", style = MaterialTheme.typography.bodySmall)
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Button(enabled = !busy, onClick = onApprove) {
                    Text("Approve")
                }
                OutlinedButton(enabled = !busy, onClick = onDeny) {
                    Text("Deny")
                }
            }
        }
    }
}

@Composable
private fun AccessMatrix(
    hosts: List<HostGate>,
    selected: HostGate,
    statuses: Map<String, HostStatus>,
    now: Long,
    enabled: Boolean,
    onSelect: (HostGate) -> Unit,
) {
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val accountWidth = 94.dp
        val hostWidth = ((maxWidth - accountWidth) / hosts.size).coerceAtLeast(94.dp)
        Row {
            Column(Modifier.width(accountWidth)) {
                MatrixLabel("Account", header = true)
                CloudAccount.entries.forEach { MatrixLabel(it.label) }
            }
            Row(Modifier.weight(1f).horizontalScroll(rememberScrollState())) {
                hosts.forEach { host ->
                    val active = host == selected
                    val colors = MaterialTheme.colorScheme
                    Surface(
                        modifier = Modifier.width(hostWidth),
                        color = if (active) colors.primaryContainer else colors.surface,
                        contentColor = if (active) colors.onPrimaryContainer else colors.onSurface,
                        shape = MaterialTheme.shapes.medium,
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            TextButton(
                                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).semantics {
                                    this.selected = active
                                },
                                enabled = enabled,
                                onClick = { onSelect(host) },
                            ) {
                                Text(host.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                            CloudAccount.entries.forEach { account ->
                                val state = accessState(host, statuses[host.id], account, now)
                                val label = when (state) {
                                    AccessState.Checking -> "Checking…"
                                    AccessState.Closed -> "Closed"
                                    AccessState.Unavailable -> "Unavailable"
                                    AccessState.NotPaired -> "Not paired"
                                    is AccessState.Open -> "Open · ${formatRemaining(state.expiresAt - now)}"
                                }
                                Box(
                                    Modifier.fillMaxWidth().heightIn(min = 42.dp).clearAndSetSemantics {
                                        contentDescription = "${host.name}, ${account.label}: $label"
                                    },
                                    contentAlignment = Alignment.Center,
                                ) {
                                    val color = when (state) {
                                        is AccessState.Open -> colors.onSecondaryContainer
                                        AccessState.Unavailable -> colors.error
                                        else -> if (active) colors.onPrimaryContainer else colors.onSurfaceVariant
                                    }
                                    Surface(
                                        color = if (state is AccessState.Open) colors.secondaryContainer
                                            else Color.Transparent,
                                        shape = MaterialTheme.shapes.small,
                                    ) {
                                        Text(
                                            label,
                                            modifier = Modifier.padding(horizontal = 5.dp, vertical = 3.dp),
                                            color = color,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                            style = MaterialTheme.typography.bodySmall,
                                            textAlign = TextAlign.Center,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun MatrixLabel(label: String, header: Boolean = false) {
    Box(
        modifier = Modifier.heightIn(min = if (header) 48.dp else 42.dp),
        contentAlignment = Alignment.CenterStart,
    ) {
        Text(
            label,
            style = if (header) MaterialTheme.typography.labelMedium else MaterialTheme.typography.bodyMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun AccountChoice(
    account: CloudAccount,
    checked: Boolean,
    enabled: Boolean,
    paired: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).toggleable(
            value = checked,
            enabled = enabled,
            role = Role.Checkbox,
            onValueChange = onCheckedChange,
        ),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(checked = checked, onCheckedChange = null, enabled = enabled)
        Text(if (paired) "Grant ${account.label}" else "${account.label} · Pair this computer")
    }
}

@Composable
private fun UpdateBanner(updateInfo: ReleaseInfo?, onUpdate: (ReleaseInfo) -> Unit) {
    updateInfo ?: return
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("New version: ${updateInfo.tagName}", style = MaterialTheme.typography.bodyMedium)
        TextButton(onClick = { onUpdate(updateInfo) }) { Text("Download update") }
    }
}

internal fun durationIndexFor(options: List<Int>, savedMinutes: Int): Int {
    val exact = options.indexOf(savedMinutes)
    return if (exact >= 0) exact else options.indexOf(60).takeIf { it >= 0 } ?: 0
}

internal fun formatDurationLabel(seconds: Long): String = when {
    seconds % 3600L == 0L -> "${seconds / 3600L}h"
    seconds % 60L == 0L -> "${seconds / 60L}m"
    else -> "${seconds}s"
}

private fun notifyPendingRequest(context: Context, req: GateClient.ApprovalRequest) {
    runCatching {
        val mgr = context.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager ?: return
        val channelId = "phone_gate_approvals"
        val channel = NotificationChannel(
            channelId,
            "Approval Requests",
            NotificationManager.IMPORTANCE_HIGH,
        )
        mgr.createNotificationChannel(channel)
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            // Deep link: opening this notification lands on this exact request.
            putExtra(KEY_FOCUS_REQUEST_ID, req.id)
        }
        val pi = PendingIntent.getActivity(
            context,
            req.id.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notif = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("${req.requester} asks for ${req.resource} (${req.scope})")
            .setContentText("${req.reason} · ${formatExpiresIn(req.expiresAt, epochSeconds())}")
            .setStyle(
                NotificationCompat.BigTextStyle().bigText(
                    "Who: ${req.requester}\nResource: ${req.resource} (${req.scope})\nWhy: ${req.reason}\n${formatExpiresIn(req.expiresAt, epochSeconds())}"
                )
            )
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()
        mgr.notify(req.id.hashCode(), notif)
    }
}

internal const val KEY_FOCUS_REQUEST_ID = "approve_request_id"

internal fun focusesRequest(req: GateClient.ApprovalRequest, focusRequestId: String?): Boolean =
    focusRequestId != null && req.id == focusRequestId

internal fun formatExpiresIn(expiresAt: Long, now: Long): String {
    val minutes = ((expiresAt - now).coerceAtLeast(0) + 59) / 60
    return "Expires: in ${minutes}m"
}

private fun epochSeconds(): Long = System.currentTimeMillis() / 1000

private fun formatRemaining(seconds: Long): String = when {
    seconds >= 3600 -> String.format(Locale.ROOT, "%dh %02dm", seconds / 3600, seconds % 3600 / 60)
    else -> String.format(Locale.ROOT, "%d:%02d", seconds / 60, seconds % 60)
}

private fun currentVersionName(context: Context): String =
    runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }.getOrNull() ?: "0.0.0"

private fun openUrl(context: Context, url: String) {
    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
}

private const val KEY_DEFAULT_DURATION_MINUTES = "default_duration_minutes"
