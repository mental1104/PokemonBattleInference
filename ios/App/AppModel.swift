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
    @Published var errorMessage: String?
    @Published var savedMessage = ""
    private var configurations: ConfigurationStore?
    private var calculator: CalculationService?
    private var calculationTask: Task<Void, Never>?
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
                return AppServices(knowledge: library, configurations: users, calculator: CalculationService(knowledge: library))
            }.value
            knowledge = services.knowledge; configurations = services.configurations; calculator = services.calculator
            natures = try await services.knowledge.natures()
            dataVersion = await services.knowledge.version().dataVersion
            serverAddress = try await services.configurations.serverURL()?.absoluteString ?? ""
            try await refreshConfigurations()
            ready = true
        } catch { present(error); started = false }
    }

    /// 从当前配置创建独立输入快照；允许取消，不把失败在线请求悄悄改成离线结果。
    func calculate(online: Bool) {
        guard !busy, let calculator, let configurations else { return }
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

    /// 保存用户明确的 HTTP(S) 地址；留空表示仅离线，凭据不写进地址。
    func saveServerAddress() async {
        guard let configurations else { return }
        do {
            let text = serverAddress.trimmingCharacters(in: .whitespacesAndNewlines)
            let value = text.isEmpty ? nil : URL(string: text)
            if !text.isEmpty && value == nil { errorMessage = "请输入完整的 http 或 https 服务器地址。"; return }
            try await configurations.setServerURL(value)
            serverAddress = value?.absoluteString ?? ""
            savedMessage = "服务器设置已保存"
        } catch { errorMessage = "服务器地址需要使用 http 或 https，且不能包含用户名或密码。" }
    }

    /// 从用户库刷新列表，禁止用内存列表冒充重启可恢复的持久化结果。
    private func refreshConfigurations() async throws { if let configurations { saved = try await configurations.all() } }

    /// 将稳定错误类别转换为用户可处理的信息，不把 SQL/C ABI 实现细节放进交互流程。
    func present(_ error: Error) {
        switch error {
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
