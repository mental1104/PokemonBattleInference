import Foundation
import SwiftUI
import PokemonAppSupport
import PokemonCore

/// 四个已实现的主入口；没有连接实际能力的任务入口不显示为假按钮。
enum AppTab: Hashable { case catalog, calculator, configurations, settings }

/// 应用 actor 的完整集合，可从后台初始化安全交给 MainActor 持有。
private struct AppServices: Sendable {
    let knowledge: KnowledgeStore
    let configurations: ConfigurationStore
    let calculator: CalculationService
    let updater: KnowledgeUpdateClient
}

/// MainActor 只管理交互与展示，SQLite 和 Core 重计算由应用支持模块执行。
@MainActor final class AppModel: ObservableObject {
    @Published var tab: AppTab = .catalog
    @Published var configuration = BattleConfiguration.example()
    @Published private(set) var knowledge: KnowledgeStore?
    @Published private(set) var natures: [NatureDetails] = []
    @Published private(set) var saved: [StoredConfiguration] = []
    @Published private(set) var result: CalculationResult?
    @Published private(set) var dataVersion = ""
    @Published private(set) var busy = false
    @Published private(set) var ready = false
    @Published var serverAddress = ""
    @Published var syncUserIdentifier = ""
    @Published private(set) var syncBusy = false
    @Published private(set) var pendingSyncCount = 0
    @Published private(set) var syncConflicts: [SyncConflict] = []
    @Published private(set) var syncMessage = ""
    @Published var errorMessage: String?
    @Published var savedMessage = ""
    @Published private(set) var connectionMessage = ""
    @Published var knowledgeManifestAddress = ""
    @Published private(set) var knowledgeUpdateBusy = false
    @Published private(set) var knowledgeUpdateProgress: KnowledgeUpdateProgress?
    @Published private(set) var knowledgeUpdateMessage = ""
    private var configurations: ConfigurationStore?
    private var calculator: CalculationService?
    private var calculationTask: Task<Void, Never>?
    private var syncTask: Task<Void, Never>?
    private var updater: KnowledgeUpdateClient?
    private var updateTask: Task<Void, Never>?
    private var started = false

    /// 初始化真实知识/用户数据库；UI 测试只使用专属 UITesting 子目录，绝不清理正常用户目录。
    func start() async {
        guard !started else { return }; started = true
        do {
            let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            let arguments = ProcessInfo.processInfo.arguments
            let testing = arguments.contains("--ui-testing")
            let directory = support.appendingPathComponent(testing ? "PokemonBattleInference-UITesting" : "PokemonBattleInference", isDirectory: true)
            let reset = testing && arguments.contains("--reset-testing-store")
            // 首次包校验与数据库打开也在后台执行，启动期间 UI 保持可绘制。
            let services = try await Task.detached {
                if reset, FileManager.default.fileExists(atPath: directory.path) { try FileManager.default.removeItem(at: directory) }
                let library = try KnowledgeStore(directory: directory.appendingPathComponent("Knowledge"), initial: KnowledgePack.bundled())
                let users = try ConfigurationStore(url: directory.appendingPathComponent("User/configurations.sqlite"))
                return AppServices(knowledge: library, configurations: users, calculator: CalculationService(knowledge: library),
                    updater: KnowledgeUpdateClient(store: library, directory: directory.appendingPathComponent("KnowledgeDownloads")))
            }.value
            knowledge = services.knowledge; configurations = services.configurations; calculator = services.calculator
            natures = try await services.knowledge.natures()
            dataVersion = await services.knowledge.version().dataVersion
            serverAddress = try await services.configurations.serverURL()?.absoluteString ?? ""
            syncUserIdentifier = try await services.configurations.syncUserIdentifier()
            updater = services.updater
            knowledgeManifestAddress = try await services.configurations.knowledgeManifestURL()?.absoluteString ?? ""
            try await refreshConfigurations()
            ready = true
        } catch { present(error); started = false }
    }

    /// 从当前配置创建独立输入快照；允许取消，不把失败在线请求悄悄改成离线结果。
    func calculate(online: Bool) {
        guard !busy, !knowledgeUpdateBusy, let calculator, let configurations else { return }
        let input = configuration
        busy = true; result = nil; savedMessage = ""
        calculationTask = Task {
            defer { busy = false; calculationTask = nil }
            do {
                let server = online ? try await configurations.serverURL() : nil
                if online && server == nil { errorMessage = "请先在设置中保存服务器地址。"; return }
                let value = try await calculator.calculate(input, server: server)
                try Task.checkCancellation()
                try await configurations.saveCalculation(configurationId: input.id, request: value.request, response: value.response,
                    engineVersion: value.engineVersion, rulesVersion: value.rulesVersion, knowledgeVersion: value.knowledgeVersion)
                result = value
            } catch is CancellationError { }
            catch { present(error) }
        }
    }

    /// 将取消传给原生令牌或 URLSession，等待实际任务结束后由 defer 恢复界面。
    func cancelCalculation() { calculationTask?.cancel() }

    /// 输入编辑后移除旧快照结果，避免把旧输入的数值显示成新配置的结果。
    func invalidateResult() { result = nil; savedMessage = "" }

    /// 保存当前完整配置及版本；另存为才创建新稳定 ID。
    func saveConfiguration(asNew: Bool = false) async {
        guard let configurations else { return }
        var input = configuration
        if asNew { input.id = UUID() }
        do {
            let value = try await configurations.save(input, knowledgeVersion: dataVersion, engineVersion: Engine.version)
            configuration = value.configuration
            try await refreshConfigurations()
            savedMessage = "已保存"
        } catch { present(error) }
    }

    /// 选择已有记录继续编辑，保持同一 ID，不复制或重新计算原始参数。
    func open(_ value: StoredConfiguration) { configuration = value.configuration; result = nil; savedMessage = ""; tab = .calculator }

    /// 删除记录保留 tombstone/变更队列，界面刷新实际 SQLite 查询结果。
    func delete(_ value: StoredConfiguration) async {
        guard let configurations else { return }
        do { try await configurations.delete(value.id); try await refreshConfigurations() }
        catch { present(error) }
    }

    /// 原子保存用户明确的 HTTP(S) 地址与同步账户；留空表示停用对应在线能力。
    func saveServerAddress() async {
        guard let configurations else { return }
        connectionMessage = ""
        do {
            let text = serverAddress.trimmingCharacters(in: .whitespacesAndNewlines)
            let value = text.isEmpty ? nil : URL(string: text)
            if !text.isEmpty && value == nil { errorMessage = "请输入完整的 http 或 https 服务器地址。"; return }
            try await configurations.setConnectionSettings(serverURL: value, userIdentifier: syncUserIdentifier)
            serverAddress = value?.absoluteString ?? ""
            syncUserIdentifier = try await configurations.syncUserIdentifier()
            connectionMessage = "连接设置已保存"
        } catch { present(error) }
    }

    /// 顺序发送持久化变更并拉取增量；只使用已保存连接，失败保留队列供下次手动重试。
    func synchronize() {
        guard !syncBusy, let configurations else { return }
        syncBusy = true; syncMessage = ""
        syncTask = Task {
            defer { syncBusy = false; syncTask = nil }
            do {
                guard let server = try await configurations.serverURL() else { errorMessage = "请先在设置中保存服务器地址和同步账户。"; return }
                let identity = try await configurations.syncUserIdentifier()
                guard !identity.isEmpty else { errorMessage = "请先在设置中填写服务端分配的同步账户。"; return }
                let client = SyncClient(store: configurations, transport: try HTTPSyncTransport(serverURL: server, userId: identity))
                let summary = try await client.synchronize()
                try await refreshConfigurations()
                syncMessage = "已提交 \(summary.accepted) 项，接收 \(summary.received) 项，待处理冲突 \(summary.conflicts) 项。"
            } catch {
                // 服务端可能已接收一部分请求；刷新真实队列，下一次仍复用未确认操作的稳定 ID。
                try? await refreshConfigurations()
                if Task.isCancelled { syncMessage = "同步已取消，未确认的修改会在下次同步时重试。" }
                else { present(error) }
            }
        }
    }

    /// 取消当前网络/队列迭代；不删除本地内容或假设服务端尚未提交。
    func cancelSynchronization() { syncTask?.cancel() }

    /// 只保存明确的知识清单来源；保存动作不会发起下载，空值表示停用更新。
    func saveKnowledgeManifestAddress() async {
        guard !knowledgeUpdateBusy, let configurations else { return }
        do {
            let text = knowledgeManifestAddress.trimmingCharacters(in: .whitespacesAndNewlines)
            let value = text.isEmpty ? nil : URL(string: text)
            if !text.isEmpty && value == nil { throw KnowledgeUpdateFailure.invalidEndpoint }
            try await configurations.setKnowledgeManifestURL(value)
            knowledgeManifestAddress = value?.absoluteString ?? ""
            knowledgeUpdateMessage = "知识来源已保存"
        } catch { present(error) }
    }

    /// 从已保存地址手动更新；失败/取消保留旧知识与部分下载，成功才刷新实际版本和性格。
    func updateKnowledge() {
        guard !knowledgeUpdateBusy, !busy, let updater, let configurations, let knowledge else { return }
        knowledgeUpdateBusy = true; knowledgeUpdateMessage = ""; knowledgeUpdateProgress = nil
        updateTask = Task {
            defer { knowledgeUpdateBusy = false; updateTask = nil }
            do {
                guard let source = try await configurations.knowledgeManifestURL() else { errorMessage = "请先保存知识清单地址。"; return }
                let current = try await updater.update(from: source) { [weak self] state in
                    Task { @MainActor [weak self] in if self?.knowledgeUpdateBusy == true { self?.knowledgeUpdateProgress = state } }
                }
                dataVersion = current.dataVersion; natures = try await knowledge.natures(); invalidateResult()
                knowledgeUpdateMessage = "知识更新完成：\(current.dataVersion)"
            } catch is CancellationError { knowledgeUpdateMessage = "更新已取消，原有知识和配置仍可使用。再次更新时会尝试续传。" }
            catch { present(error); knowledgeUpdateMessage = "更新未完成，原有知识和配置已保留，可再次更新重试。" }
        }
    }

    /// 取消真实网络任务；已完成原子提交时返回安装成功，不将新版本误报为取消。
    func cancelKnowledgeUpdate() { updateTask?.cancel() }

    /// id 是用户正查看的冲突，resolution 为明确选择；采用本地时生成新的待提交操作。
    func resolveSyncConflict(id: UUID, resolution: SyncConflictResolution) async {
        guard !syncBusy, let configurations else { return }
        do {
            try await configurations.resolveConflict(entityId: id, resolution: resolution)
            try await refreshConfigurations()
            switch resolution {
            case .keepLocal: syncMessage = "已保留此设备版本，请再次同步以提交。"
            case .keepRemote: syncMessage = "已采用服务器版本，原冲突副本已保留。"
            }
        } catch { present(error) }
    }

    /// 从真实用户库刷新配置/待提交项/冲突，保留当前未保存的编辑输入。
    private func refreshConfigurations() async throws {
        guard let configurations else { return }
        saved = try await configurations.all()
        pendingSyncCount = try await configurations.pendingChanges().count
        syncConflicts = try await configurations.syncConflicts()
    }

    /// 将稳定错误类别转换为用户可处理的信息，不把 SQL/C ABI 实现细节放进交互流程。
    func present(_ error: Error) {
        switch error {
        case KnowledgeUpdateFailure.invalidEndpoint: errorMessage = "请输入完整的 http 或 https 清单文件地址，不能包含用户名、密码、查询参数或片段。"
        case KnowledgeUpdateFailure.httpStatus(let status): errorMessage = "知识下载失败（HTTP \(status)），请检查清单地址后重试。"
        case KnowledgeUpdateFailure.responseTooLarge: errorMessage = "知识文件超过允许大小，已停止下载。原有版本仍可使用。"
        case is KnowledgeUpdateFailure: errorMessage = "知识清单或下载响应不符合要求，原有版本已保留。"
        case SyncFailure.scopeMismatch: errorMessage = "此设备的数据已关联另一个服务器或同步账户。请恢复原连接设置，现有配置和待同步修改仍被保留。"
        case SyncFailure.invalidEndpoint: errorMessage = "请检查服务器地址和同步账户，地址需要使用 http 或 https，且不能包含用户名、密码或查询参数。"
        case SyncFailure.httpStatus(let status): errorMessage = "同步未完成（HTTP \(status)），本地修改已保留。请检查服务和账户后重试。"
        case is SyncFailure: errorMessage = "同步暂未完成，本地修改已保留，请稍后重试。"
        case CalculationFailure.engineVersionMismatch: errorMessage = "服务器与本机的计算引擎版本不同，请先更新到相同版本。"
        case CalculationFailure.httpStatus(let status): errorMessage = "服务器未完成计算（HTTP \(status)）。请检查地址和服务状态。"
        case is CalculationFailure: errorMessage = "计算输入或知识数据不完整，请检查当前选择。"
        case let failure as NativeFailure where failure.status == 2: errorMessage = "当前引擎尚不支持这项招式或规则。请更换计算输入。"
        case let failure as NativeFailure where failure.status == 3: errorMessage = "这次计算超出资源限制，请缩小输入范围。"
        case is NativeFailure: errorMessage = "无法完成这次计算，请检查配置参数。"
        case StorageFailure.checksumMismatch: errorMessage = "离线知识包校验未通过，原有数据已保留。"
        case StorageFailure.unsupportedSchema: errorMessage = "当前应用不支持这个数据版本，请先更新应用。"
        case is StorageFailure: errorMessage = "无法读取或保存本地数据，请重试。"
        default: errorMessage = error.localizedDescription
        }
    }
}
