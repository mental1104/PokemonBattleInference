import SwiftUI
import PokemonAppSupport

/// 配置同步入口展示真实持久化队列与冲突；网络失败后仍可编辑和计算离线内容。
@MainActor struct SynchronizationView: View {
    @ObservedObject var model: AppModel
    /// 返回当前队列状态和可取消的同步操作，不在视图内实现协议或更改 revision。
    var body: some View {
        List {
            Section("此设备") {
                LabeledContent("待提交修改", value: String(model.pendingSyncCount)).accessibilityElement(children: .ignore)
                    .accessibilityLabel("待提交修改").accessibilityValue(String(model.pendingSyncCount)).accessibilityIdentifier("sync-pending-count")
                LabeledContent("待处理冲突", value: String(model.syncConflicts.count))
                if model.syncBusy {
                    ProgressView("正在同步")
                    Button("取消同步") { model.cancelSynchronization() }.accessibilityIdentifier("cancel-synchronization")
                } else {
                    Button("立即同步") { model.synchronize() }.accessibilityIdentifier("synchronize-now")
                }
                if !model.syncMessage.isEmpty { Text(model.syncMessage).accessibilityIdentifier("synchronization-status") }
                Text("先保存配置，再同步到其他设备。离线修改会保留到下次成功同步；未保存的编辑不会自动提交。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("需要选择的版本") {
                if model.syncConflicts.isEmpty { Text("当前没有待处理冲突。").foregroundStyle(.secondary) }
                ForEach(model.syncConflicts) { conflict in
                    NavigationLink {
                        SyncConflictView(model: model, conflict: conflict)
                    } label: {
                        VStack(alignment: .leading) {
                            Text(conflict.local.configuration.name)
                            Text("此设备与服务器都有修改，请查看后选择。")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }.accessibilityIdentifier("sync-conflict-\(conflict.id)")
                }
            }
            Section("连接") {
                Text("服务器和同步账户在设置页保存。若同步未完成，配置、待提交修改和冲突副本都会保留。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.navigationTitle("同步配置")
    }
}

/// 同时展示未决冲突的完整输入与版本；用户明确选择后才调用 SQLite 事务恢复。
@MainActor private struct SyncConflictView: View {
    @ObservedObject var model: AppModel
    let conflict: SyncConflict
    @Environment(\.dismiss) private var dismiss
    @State private var selectedResolution: SyncConflictResolution?
    /// 两份内容均来自持久化冲突快照，删除也展示原配置，避免凭名称决定覆盖。
    var body: some View {
        List {
            snapshot(conflict.local.configuration, deleted: conflict.local.deleted,
                knowledgeVersion: conflict.local.knowledgeVersion, engineVersion: conflict.local.engineVersion,
                revision: conflict.local.serverRevision, title: "此设备版本")
            if let remote = conflict.remote {
                snapshot(remote.configuration, deleted: remote.deleted, knowledgeVersion: remote.knowledgeVersion,
                    engineVersion: remote.engineVersion, revision: remote.revision, title: "服务器版本")
            } else { Section("服务器版本") { Text("服务器没有这条配置。") } }
            Section("选择采用的版本") {
                Button("使用此设备版本") { selectedResolution = .keepLocal }.accessibilityIdentifier("keep-local-configuration")
                Button("使用服务器版本") { selectedResolution = .keepRemote }.accessibilityIdentifier("keep-remote-configuration")
                Text("使用此设备版本后需要再次同步。选择服务器版本会更新此设备的配置；原冲突副本仍会保留。")
                    .font(.caption).foregroundStyle(.secondary)
            }.disabled(model.syncBusy)
        }.navigationTitle("比较冲突")
        .confirmationDialog("采用所选版本？", isPresented: Binding(get: { selectedResolution != nil }, set: { if !$0 { selectedResolution = nil } })) {
            if let resolution = selectedResolution {
                Button("确认采用") {
                    Task {
                        await model.resolveSyncConflict(id: conflict.id, resolution: resolution)
                        if !model.syncConflicts.contains(where: { $0.id == conflict.id }) { dismiss() }
                    }
                }
            }
            Button("继续比较", role: .cancel) { selectedResolution = nil }
        } message: { Text("只有确认后才会更新此设备的数据。") }
    }

    /// configuration 为完整本地/远端输入；deleted 保留删除语义，其余参数展示该快照的实际版本。
    /// 返回只读分组，包含双方全部能力配置和环境，不执行或重算任何战斗规则。
    private func snapshot(_ configuration: BattleConfiguration, deleted: Bool, knowledgeVersion: String,
                          engineVersion: String, revision: Int64, title: String) -> some View {
        Section(title) {
            LabeledContent("状态", value: deleted ? "已删除" : "保留配置")
            LabeledContent("名称", value: configuration.name)
            LabeledContent("服务器版本", value: String(revision))
            pokemon(configuration.attacker, title: "攻击方")
            pokemon(configuration.defender, title: "防守方")
            LabeledContent("招式编号", value: String(configuration.moveId))
            LabeledContent("世代", value: String(configuration.generationId))
            LabeledContent("天气", value: configuration.weather.displayName)
            LabeledContent("场地", value: configuration.terrain.displayName)
            LabeledContent("要害", value: configuration.critical ? "是" : "否")
            LabeledContent("引擎", value: engineVersion)
            LabeledContent("知识", value: knowledgeVersion)
        }
    }

    /// configuration 为一方已保存的完整配置，title 区分攻守；仅格式化六项参数供人工比较。
    private func pokemon(_ configuration: PokemonConfiguration, title: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(title)：#\(configuration.pokemonId) · Lv.\(configuration.level)").font(.headline)
            Text("性格编号 \(configuration.natureId) · \(configuration.ability.displayName) · \(configuration.item.displayName)")
            Text("IV：\(stats(configuration.ivs))")
            Text("EV：\(stats(configuration.evs))")
            Text(configuration.paralyzed ? "麻痹" : "未麻痹")
        }.font(.caption)
    }

    /// value 为已保存六项整数，返回按生命/攻击/防御/特攻/特防/速度顺序的可读文本。
    private func stats(_ value: StatValues) -> String {
        "生命 \(value.hp) / 攻 \(value.attack) / 防 \(value.defense) / 特攻 \(value.specialAttack) / 特防 \(value.specialDefense) / 速 \(value.speed)"
    }
}
