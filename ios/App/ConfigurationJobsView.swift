import SwiftUI
import PokemonAppSupport

/// 最简真实任务入口：独立旧合同表单、服务器进度、明确取消和分页精确结果。
@MainActor struct ConfigurationJobsView: View {
    @ObservedObject var model: AppModel
    @StateObject private var jobs = ConfigurationJobsModel()
    /// 任务配置与离线直接伤害编辑器分开，避免把任意IV/EV默默替换成固定模板。
    var body: some View {
        Form {
            if jobs.jobId.isEmpty {
                Section("共同条件") {
                    Stepper("双方等级：\(jobs.command.attacker.fixed.level)", value: Binding(get: { jobs.command.attacker.fixed.level }, set: {
                        jobs.command.attacker.fixed.level = $0; jobs.command.defender.fixed.level = $0
                    }), in: 1...100)
                }.disabled(jobs.working)
                Section("攻击方") {
                    JobSideEditor(value: $jobs.command.attacker.fixed)
                    TextField("候选招式ID，英文逗号分隔", text: $jobs.attackerMoves).keyboardType(.numbersAndPunctuation)
                        .accessibilityIdentifier("job-attacker-moves")
                }
                Section("防御方") {
                    JobSideEditor(value: $jobs.command.defender.fixed)
                    TextField("候选招式ID，英文逗号分隔", text: $jobs.defenderMoves).keyboardType(.numbersAndPunctuation)
                        .accessibilityIdentifier("job-defender-moves")
                }
                Section("规则与预算") {
                    TextField("规则集", text: $jobs.command.rulesetId).textInputAutocapitalization(.never).autocorrectionDisabled()
                    LabeledContent("版本组") { TextField("版本组ID", value: $jobs.command.versionGroupId, format: .number).keyboardType(.numberPad) }
                    TextField("计算修订", text: $jobs.command.calculationRevision).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Picker("攻击方策略", selection: $jobs.command.attackerPolicy) { ForEach(JobActionPolicy.allCases, id: \.self) { Text($0.displayName).tag($0) } }
                    Picker("防御方策略", selection: $jobs.command.defenderPolicy) { ForEach(JobActionPolicy.allCases, id: \.self) { Text($0.displayName).tag($0) } }
                    LabeledContent("每配置对节点上限") { TextField("节点上限", value: $jobs.command.execution.maxNodesPerPair, format: .number).keyboardType(.numberPad) }
                    LabeledContent("每配置对边上限") { TextField("边上限", value: $jobs.command.execution.maxEdgesPerPair, format: .number).keyboardType(.numberPad) }
                    Text("固定双方物种、等级、能力模板、特性和道具，枚举各1至10个候选招式。规则、支持范围与图预算由服务和Core验证。能力模板是原服务公开key，不使用离线编辑器的IV/EV。")
                        .font(.caption).foregroundStyle(.secondary)
                }.disabled(jobs.working)
                Section {
                    Button("提交推演任务") { Task { await withServer { await jobs.submit(to: $0) } } }
                        .disabled(jobs.working).accessibilityIdentifier("submit-configuration-job")
                    if !jobs.requestKey.isEmpty { Text("请求键：\(jobs.requestKey)").font(.caption).textSelection(.enabled) }
                }
            }
            Section("查看已有任务") {
                TextField("任务ID", text: $jobs.lookupId).textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("job-lookup-id")
                Button("查询任务") { Task { await withServer { await jobs.openExisting(on: $0) } } }.disabled(jobs.working).accessibilityIdentifier("lookup-configuration-job")
            }
            if !jobs.jobId.isEmpty {
                Section("当前任务") {
                    Text(jobs.jobId).textSelection(.enabled).accessibilityIdentifier("configuration-job-id")
                    LabeledContent("服务器", value: jobs.serverName)
                    if let status = jobs.status {
                        LabeledContent("状态", value: status.status.displayName).accessibilityElement(children: .ignore)
                            .accessibilityLabel("状态").accessibilityValue(status.status.displayName).accessibilityIdentifier("configuration-job-phase")
                        ProgressView(value: Double(status.counts.completed), total: Double(max(1, status.counts.total))) {
                            Text("已完成 \(status.counts.completed) / \(status.counts.total)")
                        }
                        Text("成功 \(status.counts.succeeded) · 失败 \(status.counts.failed) · 截断 \(status.counts.truncated) · 取消 \(status.counts.cancelled)").font(.caption)
                        LabeledContent("节点", value: "\(status.stateNodes.used) / \(status.stateNodes.limit)")
                        LabeledContent("边", value: "\(status.stateEdges.used) / \(status.stateEdges.limit)")
                        Text("\(status.rulesetId) · 版本组\(status.versionGroupId) · \(status.calculationRevision)").font(.caption).foregroundStyle(.secondary)
                        if status.cancellationRequested { Text("服务器已收到取消请求，等待终态确认。") }
                        if let code = status.lastFailureCode { Text("失败：\(code) · \(status.lastFailureDiagnostic ?? "")").foregroundStyle(.red) }
                        if !status.status.terminal {
                            Button("请求服务器取消", role: .destructive) { Task { await jobs.cancelOnServer() } }
                                .disabled(jobs.working).accessibilityIdentifier("cancel-configuration-job")
                        }
                    }
                    Button(jobs.polling ? "正在轮询 · 手动刷新" : "刷新状态") { Task { await jobs.refresh() } }.disabled(jobs.working)
                    Button("开始另一个任务") { jobs.prepareAnother() }.disabled(jobs.working)
                    Text("离开页面只停止查询，后台任务继续运行。开始另一个任务也不会取消原任务，请先复制任务ID。")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if !jobs.message.isEmpty { Section { Text(jobs.message).accessibilityIdentifier("configuration-job-message") } }
            if !jobs.cases.isEmpty {
                Section("配置对结果") {
                    ForEach(jobs.cases) { item in
                        NavigationLink {
                            JobCaseView(item: item, loadMetadata: { try await jobs.executionMetadata(for: item.configurationId) }).navigationTitle("配置对结果")
                        } label: { Text("#\(item.sequenceNo + 1) · \(item.status.rawValue)") }
                            .accessibilityIdentifier("configuration-job-case-\(item.sequenceNo)")
                    }
                    if jobs.nextOffset != nil { Button("加载下一页") { Task { await jobs.loadMore() } }.disabled(jobs.working) }
                }
            }
            if jobs.working { ProgressView("等待服务器响应") }
        }.scrollDismissesKeyboard(.interactively).navigationTitle("在线推演任务")
            .task { if !jobs.jobId.isEmpty { await jobs.refresh() } }
            .onDisappear { jobs.stopPolling() }
            .alert("任务操作未完成", isPresented: Binding(get: { jobs.errorMessage != nil }, set: { if !$0 { jobs.errorMessage = nil } })) {
                Button("好", role: .cancel) { jobs.errorMessage = nil }
            } message: { Text(jobs.errorMessage ?? "") }
    }

    /// action 接收SQLite中明确保存的地址；未保存或存储失败由共享错误界面说明。
    private func withServer(_ action: @MainActor (URL) async -> Void) async {
        do {
            guard let server = try await model.savedServerURL() else { model.errorMessage = "请先在设置中保存服务器地址。"; return }
            await action(server)
        } catch { model.present(error) }
    }
}

/// 一侧固定HTTP字段输入；能力模板/特性/道具使用服务公开标识，不在Swift注入倍率或能力值。
@MainActor private struct JobSideEditor: View {
    @Binding var value: JobFixedPokemon
    /// value 为原合同的固定侧，不是离线直接伤害编辑器的替代映射。
    var body: some View {
        LabeledContent("宝可梦编号") { TextField("编号", value: $value.pokemonId, format: .number).keyboardType(.numberPad) }
        TextField("能力模板key", text: $value.statProfileId).textInputAutocapitalization(.never).autocorrectionDisabled()
        TextField("特性identifier", text: $value.abilityIdentifier).textInputAutocapitalization(.never).autocorrectionDisabled()
        TextField("道具identifier（留空为无）", text: Binding(get: { value.itemIdentifier ?? "" }, set: { value.itemIdentifier = $0.isEmpty ? nil : $0 }))
            .textInputAutocapitalization(.never).autocorrectionDisabled()
    }
}

/// 呈现服务实际摘要；nil概率保留“暂无”，不把失败/截断解释成零胜率。
@MainActor private struct JobCaseView: View {
    let item: ConfigurationJobCase
    /// 来自当前任务冻结client的只读查询；不读取可编辑设置，也不从业务解释提取版本。
    let loadMetadata: @MainActor () async throws -> ConfigurationJobExecutionMetadata?
    @State private var metadata: ConfigurationJobExecutionMetadata?
    @State private var loading = true
    @State private var metadataError = false
    /// 精确分数和期望回合均为服务返回的字符串，展示小数不重新参与业务计算。
    var body: some View {
        Form {
            Text("\(item.attackerPokemonId)：\(item.attackerMoveIds.map(String.init).joined(separator: ",")) → \(item.defenderPokemonId)：\(item.defenderMoveIds.map(String.init).joined(separator: ","))").font(.caption)
            metric("攻击方胜率", value: item.attackerWinProbability?.text ?? "暂无结果", id: "job-result-attacker-win")
            metric("防御方胜率", value: item.defenderWinProbability?.text ?? "暂无结果", id: "job-result-defender-win")
            metric("平局率", value: item.drawProbability?.text ?? "暂无结果", id: "job-result-draw")
            metric("期望回合", value: item.expectedTurns ?? item.expectedTurnsKind?.rawValue ?? "暂无结果", id: "job-result-expected-turns")
            LabeledContent("节点/边", value: "\(item.nodeCount) / \(item.edgeCount)")
            if let code = item.failureCode { Text("\(code) · \(item.diagnostic ?? "")").foregroundStyle(.red) }
            metric("推演引擎", value: versionText(metadata?.engineVersion), id: "job-result-engine")
            metric("推演规则", value: versionText(metadata?.rulesVersion), id: "job-result-rules")
            if metadataError { Button("运行信息读取失败，重试") { Task { await readMetadata() } }.accessibilityIdentifier("retry-job-metadata") }
            if let metadata { Text("输入 SHA-256：\(metadata.inputSha256)").font(.caption2).textSelection(.enabled) }
            Text(item.configurationId).font(.caption2).textSelection(.enabled)
            // 查询绑定详情容器生命周期；滚动回收某个Form结果行不能取消来源请求。
        }.task(id: item.configurationId) { await readMetadata() }
    }
    /// value 只接受独立溯源版本；加载/网络失败/旧记录分别显示，绝不读取 explanation 或本地引擎替代。
    private func versionText(_ value: String?) -> String { loading ? "读取中" : metadataError ? "读取失败" : value ?? "未知（未记录）" }
    /// 调用已冻结任务的只读接口；取消不更新离开的视图，失败不污染原业务结果。
    private func readMetadata() async {
        loading = true; metadataError = false
        do { let value = try await loadMetadata(); try Task.checkCancellation(); metadata = value; loading = false }
        catch { if !Task.isCancelled { metadataError = true; loading = false } }
    }
    /// title/value 为服务结果名称/原文；id提供稳定无障碍语义，不依赖合并后的标签解析数值。
    private func metric(_ title: String, value: String, id: String) -> some View {
        LabeledContent(title, value: value).accessibilityElement(children: .ignore).accessibilityLabel(title).accessibilityValue(value).accessibilityIdentifier(id)
    }
}

/// 只翻译原HTTP策略名称，不决定行动规则。
extension JobActionPolicy {
    /// 可读策略名称。
    var displayName: String { switch self { case .firstLegalAction: "首个合法行动"; case .uniformRandom: "均匀随机" } }
}
/// 只翻译原轮询粗状态，取消请求不会预先显示成取消终态。
extension ConfigurationJobPhase {
    /// 可读实际任务状态。
    var displayName: String { switch self { case .queued: "排队中"; case .running: "运行中"; case .completed: "已完成"; case .partial: "部分完成"; case .cancelled: "已取消"; case .failed: "失败" } }
}
