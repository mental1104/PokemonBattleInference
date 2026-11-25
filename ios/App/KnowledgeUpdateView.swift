import SwiftUI
import PokemonAppSupport

/// 手动网络更新入口；仅显示真实下载字节，取消和失败后允许重试，不触碰用户配置。
@MainActor struct KnowledgeUpdateView: View {
    @ObservedObject var model: AppModel
    @FocusState private var editingAddress: Bool
    /// 来源需先保存再更新，避免编辑未保存的地址意外发起网络访问。
    var body: some View {
        Form {
            Section("当前版本") { Text(model.dataVersion).textSelection(.enabled).accessibilityIdentifier("installed-knowledge-version") }
            Section("更新来源") {
                TextField("https://服务器/知识目录/manifest.json", text: $model.knowledgeManifestAddress)
                    .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .focused($editingAddress).submitLabel(.done).onSubmit { editingAddress = false }
                    .accessibilityIdentifier("knowledge-manifest-url").disabled(model.knowledgeUpdateBusy)
                Button("保存知识来源") { editingAddress = false; Task { await model.saveKnowledgeManifestAddress() } }
                    .accessibilityIdentifier("save-knowledge-source").disabled(model.knowledgeUpdateBusy)
                Text("清单地址由您提供；数据库必须放在同一目录，文件名为 knowledge.sqlite。只在点击更新后访问网络，拒绝重定向。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("更新") {
                if model.knowledgeUpdateBusy {
                    if let state = model.knowledgeUpdateProgress { updateProgress(state) }
                    else { ProgressView("准备更新") }
                    Button("取消更新", role: .cancel) { model.cancelKnowledgeUpdate() }.accessibilityIdentifier("cancel-knowledge-update")
                } else {
                    Button("下载并更新知识") { editingAddress = false; model.updateKnowledge() }
                        .accessibilityIdentifier("download-knowledge-update").disabled(model.busy)
                }
                if !model.knowledgeUpdateMessage.isEmpty { Text(model.knowledgeUpdateMessage).accessibilityIdentifier("knowledge-update-status") }
                Text("清单不超过1 MiB，数据库不超过64 MiB。下载中断或取消会保留已收到的字节，重试时尝试续传；服务器不支持续传时从头下载。大小、SHA-256 和数据库内容校验通过后才切换版本，原版本文件和用户配置始终保留。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.scrollDismissesKeyboard(.interactively).navigationTitle("更新离线知识")
    }
    /// state 是实际客户端反馈，只有已知数据库总长时才显示确定进度。
    @ViewBuilder private func updateProgress(_ state: KnowledgeUpdateProgress) -> some View {
        switch state {
        case .fetchingManifest: ProgressView("读取知识清单")
        case .downloading(let received, let total):
            ProgressView(value: Double(received), total: Double(total)) { Text("已下载 \(received) / \(total) 字节") }
                .accessibilityIdentifier("knowledge-download-progress")
        case .validating: ProgressView("校验下载内容")
        case .installing: ProgressView("安装并切换知识版本")
        }
    }
}
