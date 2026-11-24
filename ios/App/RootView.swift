import SwiftUI
import PokemonAppSupport
import PokemonCore

/// 四个入口共享同一用户库；启动失败可重试，错误信息保持在当前操作上下文。
@MainActor struct RootView: View {
    @ObservedObject var model: AppModel
    /// 根据真实初始化状态选择加载界面或完整应用。
    var body: some View {
        Group {
            if model.ready, let knowledge = model.knowledge {
                TabView(selection: $model.tab) {
                    CatalogView(knowledge: knowledge).tabItem { Label("图鉴", systemImage: "books.vertical") }.tag(AppTab.catalog)
                    CalculatorView(model: model, knowledge: knowledge).tabItem { Label("计算", systemImage: "function") }.tag(AppTab.calculator)
                    ConfigurationsView(model: model).tabItem { Label("配置", systemImage: "tray.full") }.tag(AppTab.configurations)
                    SettingsView(model: model).tabItem { Label("设置", systemImage: "gearshape") }.tag(AppTab.settings)
                }
            } else {
                VStack(spacing: 20) {
                    ProgressView("正在准备离线图鉴")
                    Button("重新加载") { Task { await model.start() } }
                }
            }
        }
        .alert("操作未完成", isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })) {
            Button("好", role: .cancel) { model.errorMessage = nil }
        } message: { Text(model.errorMessage ?? "") }
    }
}

/// 保存列表直接来自用户 SQLite；打开后继续编辑相同记录，删除也更新真实持久化状态。
@MainActor private struct ConfigurationsView: View {
    @ObservedObject var model: AppModel
    /// 展示已保存配置或明确的空状态。
    var body: some View {
        NavigationStack {
            List {
                Section {
                    NavigationLink { SynchronizationView(model: model) } label: {
                        Label("同步配置（待提交 \(model.pendingSyncCount) 项）", systemImage: "arrow.triangle.2.circlepath")
                    }.accessibilityIdentifier("open-synchronization")
                    if !model.syncConflicts.isEmpty { Text("有 \(model.syncConflicts.count) 项冲突需要选择版本。").foregroundStyle(.orange) }
                }
                if model.saved.isEmpty {
                    Text("还没有保存的配置。请到计算页编辑并保存。").foregroundStyle(.secondary)
                }
                ForEach(model.saved) { record in
                    Button { model.open(record) } label: {
                        VStack(alignment: .leading) {
                            Text(record.configuration.name)
                            Text("本地编辑 \(record.localSequence) · 服务器版本 \(record.serverRevision)").font(.caption).foregroundStyle(.secondary)
                        }
                    }.accessibilityIdentifier("saved-configuration-\(record.id)")
                    .swipeActions { Button("删除", role: .destructive) { Task { await model.delete(record) } } }
                }
            }.navigationTitle("配置")
        }
    }
}

/// 服务地址为可选设置；离线查询和计算不依赖网络或登录。
@MainActor private struct SettingsView: View {
    @ObservedObject var model: AppModel
    /// 展示实际运行版本，保存用户输入的服务根地址。
    var body: some View {
        NavigationStack {
            Form {
                Section("服务器") {
                    TextField("http://服务器:端口", text: $model.serverAddress).textInputAutocapitalization(.never)
                        .autocorrectionDisabled().keyboardType(.URL).submitLabel(.done).accessibilityIdentifier("server-address")
                    TextField("服务端分配的同步账户", text: $model.syncUserIdentifier).textInputAutocapitalization(.never)
                        .autocorrectionDisabled().submitLabel(.done).accessibilityIdentifier("sync-user")
                    Button("保存连接设置") { Task { await model.saveServerAddress() } }.accessibilityIdentifier("save-server")
                    Text("留空时使用离线模式。在线计算向此地址发送当前计算参数；同一引擎版本才接受结果。").font(.caption).foregroundStyle(.secondary)
                    Text("两台设备使用同一服务器和同步账户即可共享已保存配置。同步账户由服务端分配。").font(.caption).foregroundStyle(.secondary)
                    if !model.connectionMessage.isEmpty { Text(model.connectionMessage).accessibilityIdentifier("settings-save-status") }
                }
                Section("版本") {
                    LabeledContent("引擎", value: Engine.version)
                    LabeledContent("离线知识", value: model.dataVersion)
                }
                Section("当前计算范围") {
                    Text("支持单次直接伤害、能力值、速度与精确的一击/两击 KO 概率。特性、道具与环境仅可选择界面列出的已实现规则；特殊威力或变化招式会明确提示不支持。")
                }
            }.scrollDismissesKeyboard(.interactively).navigationTitle("设置")
        }
    }
}
