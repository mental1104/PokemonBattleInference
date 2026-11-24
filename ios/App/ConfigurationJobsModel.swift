import Foundation
import SwiftUI
import PokemonAppSupport

/// 单个真实后台任务的最简界面状态；只轮询正式HTTP，不执行配置枚举、战斗或概率算法。
@MainActor final class ConfigurationJobsModel: ObservableObject {
    @Published var command = ConfigurationJobCommand(
        attacker: JobMovePool(fixed: JobFixedPokemon(pokemonId: 212, statProfileId: "max_atk_plus", abilityIdentifier: "technician"), candidateMoveIds: [404]),
        defender: JobMovePool(fixed: JobFixedPokemon(pokemonId: 149, statProfileId: "max_hp_def_plus", abilityIdentifier: "multiscale"), candidateMoveIds: [337]),
        execution: JobExecutionBudget(processCount: 1, queueDepth: 1))
    @Published var attackerMoves = "404"
    @Published var defenderMoves = "337"
    @Published var lookupId = ""
    @Published private(set) var jobId = ""
    @Published private(set) var serverName = ""
    @Published private(set) var status: ConfigurationJobStatus?
    @Published private(set) var cases: [ConfigurationJobCase] = []
    @Published private(set) var nextOffset: Int?
    @Published private(set) var working = false
    @Published private(set) var polling = false
    @Published private(set) var requestKey = ""
    @Published private(set) var message = ""
    @Published var errorMessage: String?
    private var client: ConfigurationJobClient?
    private var pendingCommand: ConfigurationJobCommand?
    private var pendingServer: URL?
    private var pollTask: Task<Void, Never>?
    private var pollGeneration = UUID()

    /// server 为已保存根地址；请求不确定失败时保留同一命令/地址/key，重试不会静默创建重复任务。
    func submit(to server: URL) async {
        guard !working, jobId.isEmpty else { return }
        working = true; message = ""
        defer { working = false }
        do {
            var input = command
            input.attacker.candidateMoveIds = try moveIds(attackerMoves)
            input.defender.candidateMoveIds = try moveIds(defenderMoves)
            if pendingCommand != input || pendingServer != server || requestKey.isEmpty {
                pendingCommand = input; pendingServer = server; requestKey = UUID().uuidString
            }
            let next = try ConfigurationJobClient(serverURL: server)
            let acknowledgement = try await next.submit(input, idempotencyKey: requestKey)
            client = next; jobId = acknowledgement.jobId; lookupId = acknowledgement.jobId; serverName = server.host ?? ""
            message = "服务器已接收 \(acknowledgement.submittedConfigurationPairs) 个配置对，计算尚未完成。"
            try await refreshOnce()
            startPolling()
        } catch { present(error) }
    }

    /// server 为当前已保存地址；lookupId是用户复制的真实job ID，失败时保留原先查看的任务。
    func openExisting(on server: URL) async {
        guard !working else { return }
        working = true; defer { working = false }
        do {
            let id = lookupId.trimmingCharacters(in: .whitespacesAndNewlines)
            let next = try ConfigurationJobClient(serverURL: server), value = try await next.status(id)
            stopPolling(); client = next; jobId = id; serverName = server.host ?? ""; status = value
            cases = []; nextOffset = nil; message = ""
            try await fetchResults(offset: 0); startPolling()
        } catch { present(error) }
    }

    /// 刷新已绑定任务；不会因为设置页地址被编辑而把旧任务发送到另一台服务器。
    func refresh() async {
        guard !working, client != nil else { return }
        stopPolling(); working = true; defer { working = false }
        do { try await refreshOnce(); startPolling() } catch { present(error) }
    }

    /// 明确向服务端提交取消，取消请求可能与完成交错；只有真实轮询终态才能确认结果。
    func cancelOnServer() async {
        guard !working, let client else { return }
        stopPolling(); working = true; defer { working = false }
        do {
            let acknowledgement = try await client.cancel(jobId)
            message = acknowledgement.cancellationRequested ? "取消请求已保存，等待服务器确认终态。" : "服务器当前状态：\(acknowledgement.status.rawValue)。"
            try await refreshOnce(); startPolling()
        } catch { present(error); startPolling() }
    }

    /// 加载服务返回的下一稳定结果页，保留成功/失败/截断条目而不只挑选成功结果。
    func loadMore() async {
        guard !working, let offset = nextOffset else { return }
        working = true; defer { working = false }
        do { try await fetchResults(offset: offset) } catch { present(error) }
    }

    /// 开始另一个任务只清理本地显示，不取消或删除原任务；job ID可先复制保存以便继续查询。
    func prepareAnother() {
        guard !working else { return }
        stopPolling(); client = nil; jobId = ""; status = nil; cases = []; nextOffset = nil
        requestKey = ""; pendingCommand = nil; pendingServer = nil; message = ""
    }

    /// 离开页面只停止轮询，不给服务端发送取消请求；返回页面后可手动刷新。
    func stopPolling() { pollGeneration = UUID(); pollTask?.cancel(); pollTask = nil; polling = false }

    /// 轮询只按实际服务响应刷新；网络故障停止并保留job ID，用户可刷新重连。
    private func startPolling() {
        guard let client, let status, !status.status.terminal else { return }
        stopPolling(); let generation = pollGeneration, id = jobId
        polling = true
        pollTask = Task {
            defer { if generation == pollGeneration { polling = false; pollTask = nil } }
            do {
                while true {
                    try await Task.sleep(for: .seconds(1))
                    let value = try await client.status(id)
                    try Task.checkCancellation()
                    guard generation == pollGeneration, id == jobId else { return }
                    self.status = value
                    if value.status.terminal { try await fetchResults(offset: 0); return }
                }
            } catch is CancellationError { }
            catch { if !Task.isCancelled { present(error) } }
        }
    }

    /// 从实际服务同时刷新状态和首个结果页；计数/资源不根据墙钟估算。
    private func refreshOnce() async throws {
        guard let client else { return }
        let value = try await client.status(jobId)
        try Task.checkCancellation(); status = value
        try await fetchResults(offset: 0)
    }

    /// offset 为原API的0起点序号；服务返回opaque nextCursor保持原样，仅此原合同整数游标转换用于分页。
    private func fetchResults(offset: Int) async throws {
        guard let client else { return }
        let page = try await client.results(jobId, offset: offset)
        try Task.checkCancellation()
        if offset == 0 { cases = page.items } else { cases.append(contentsOf: page.items) }
        if let cursor = page.nextCursor {
            guard let next = Int(cursor), next > offset else { throw ConfigurationJobFailure.invalidResponse }
            nextOffset = next
        } else { nextOffset = nil }
    }

    /// text 是逗号分隔的原始候选ID；只解析输入，不排序/去重/准入或执行配置枚举。
    private func moveIds(_ text: String) throws -> [Int64] {
        let fields = text.split(separator: ",", omittingEmptySubsequences: false)
        guard (1...10).contains(fields.count) else { throw ConfigurationJobFailure.invalidInput }
        return try fields.map {
            guard let id = Int64($0.trimmingCharacters(in: .whitespacesAndNewlines)), id > 0 else { throw ConfigurationJobFailure.invalidInput }; return id
        }
    }

    /// error 是实际操作错误；不展示伪成功或将未确认的POST自动重复成另一任务。
    private func present(_ error: Error) {
        switch error {
        case ConfigurationJobFailure.httpStatus(let status, _):
            let detail = (error as? ConfigurationJobFailure)?.serverDetail ?? "请检查配置、服务状态和支持范围。"
            errorMessage = "服务器未完成任务操作（HTTP \(status)）：\(detail)\n任务ID与请求键已保留。"
        case ConfigurationJobFailure.invalidInput: errorMessage = "请检查输入：候选招式为1至10个正整数，用英文逗号分隔；任务ID不能为空或包含路径。"
        case ConfigurationJobFailure.invalidEndpoint: errorMessage = "请在设置中保存完整的 http 或 https 服务器地址。"
        case is ConfigurationJobFailure: errorMessage = "服务器的任务响应无法读取。任务ID已保留，请检查服务版本后重试。"
        case is URLError: errorMessage = "网络连接未完成。任务和提交结果可能仍在服务端，请保留任务ID；重试提交会使用原请求键。"
        default: errorMessage = "任务操作未完成，请稍后刷新重试。"
        }
    }
}
