import SwiftUI
import PokemonAppSupport

/// 图鉴查询模式，同时用于配置编辑中的真实数据库选择器。
enum CatalogKind: String, CaseIterable { case pokemon = "宝可梦", move = "招式" }

/// 分页读取真实离线 SQLite；NavigationSplitView 自动适配 iPhone 和 iPad。
@MainActor struct CatalogView: View {
    let knowledge: KnowledgeStore
    @State private var kind = CatalogKind.pokemon
    @State private var query = ""
    @State private var pokemon: [PokemonSummary] = []
    @State private var moves: [MoveDetails] = []
    @State private var limit = 100
    @State private var error: String?
    /// 列表按搜索词/模式/页数取消旧查询，避免旧结果覆盖当前输入。
    var body: some View {
        NavigationSplitView {
            List {
                Picker("类型", selection: $kind) { ForEach(CatalogKind.allCases, id: \.self) { Text($0.rawValue).tag($0) } }.pickerStyle(.segmented)
                if let error { Text(error).foregroundStyle(.red) }
                if kind == .pokemon {
                    ForEach(pokemon) { item in NavigationLink { PokemonDetailView(knowledge: knowledge, id: item.id) } label: { CatalogRow(title: item.name, identifier: item.identifier, id: item.id, icon: .pokemon(item.id)) }.accessibilityIdentifier("pokemon-\(item.id)") }
                } else {
                    ForEach(moves) { item in NavigationLink { MoveDetailView(knowledge: knowledge, move: item) } label: { CatalogRow(title: item.name, identifier: item.identifier, id: item.id, icon: .elementType(item.typeId)) }.accessibilityIdentifier("move-\(item.id)") }
                }
                if (kind == .pokemon ? pokemon.count : moves.count) == limit {
                    Button("加载更多") { limit += 100 }
                }
                if error == nil && (kind == .pokemon ? pokemon.isEmpty : moves.isEmpty) { Text("没有匹配的条目").foregroundStyle(.secondary) }
            }.navigationTitle("离线图鉴").searchable(text: $query, prompt: "名称、英文或编号")
                .task(id: "\(kind.rawValue)|\(query)|\(limit)") { await search() }
        } detail: { Text("选择宝可梦或招式查看详情").foregroundStyle(.secondary) }
    }
    /// 返回当前搜索的数据库结果；取消时保持新任务负责刷新，不展示取消错误。
    private func search() async {
        do {
            if kind == .pokemon { let value = try await knowledge.searchPokemon(query, limit: limit); try Task.checkCancellation(); pokemon = value }
            else { let value = try await knowledge.searchMoves(query, limit: limit); try Task.checkCancellation(); moves = value }
            error = nil
        } catch is CancellationError { } catch { self.error = "无法读取离线图鉴" }
    }
}

/// 名称与英文 identifier 同时展示，避免不同形态只有同一中文名而无法区分。
@MainActor private struct CatalogRow: View {
    let title: String
    let identifier: String
    let id: Int64
    let icon: BundledIcon
    /// 编号和名称仍来自知识库；icon只补充离线视觉识别，不参与搜索或规则计算。
    var body: some View {
        HStack {
            OfflineIconView(icon: icon, label: title)
            VStack(alignment: .leading) { Text(title); Text("#\(id) · \(identifier)").font(.caption).foregroundStyle(.secondary) }
        }
    }
}

/// 按稳定知识 ID 读取种族值、属性和特性，不从显示名称猜测数据。
@MainActor private struct PokemonDetailView: View {
    let knowledge: KnowledgeStore
    let id: Int64
    @State private var details: PokemonDetails?
    @State private var failed = false
    /// 详情读取保持在知识 actor，界面只进行尺寸的单位格式化。
    var body: some View {
        Form {
            if let details {
                Section("资料") {
                    HStack { Spacer(); OfflineIconView(icon: .pokemon(id), label: details.summary.name, size: 96); Spacer() }
                    Text(details.summary.identifier)
                    LabeledContent("编号", value: String(id))
                    LabeledContent("属性", value: details.types.map(\.name).joined(separator: " / "))
                    LabeledContent("身高", value: String(format: "%.1f m", Double(details.height) / 10))
                    LabeledContent("体重", value: String(format: "%.1f kg", Double(details.weight) / 10))
                }
                Section("种族值") { StatSummary(values: details.baseStats) }
                Section("特性") { ForEach(details.abilities) { Text($0.name + ($0.hidden ? "（隐藏）" : "")) } }
            } else if failed { Text("无法读取这项资料") } else { ProgressView() }
        }.navigationTitle(details?.summary.name ?? "详情").task {
            do { details = try await knowledge.pokemon(id) } catch { failed = true }
        }
    }
}

/// 招式详情沿用知识包的可空威力与命中率，不把缺失值解释为零。
@MainActor private struct MoveDetailView: View {
    let knowledge: KnowledgeStore
    let move: MoveDetails
    @State private var typeName = ""
    /// 原始分类与优先度供查询使用，计算支持性由引擎单独判断。
    var body: some View {
        Form {
            Text(move.identifier)
            LabeledContent("属性", value: typeName)
            LabeledContent("分类", value: move.category.displayName)
            LabeledContent("威力", value: move.power.map(String.init) ?? "—")
            LabeledContent("命中率", value: move.accuracy.map { "\($0)%" } ?? "—")
            LabeledContent("PP", value: move.pp.map(String.init) ?? "—")
            LabeledContent("优先度", value: String(move.priority))
        }.navigationTitle(move.name).task {
            do { typeName = try await knowledge.types().first { $0.id == move.typeId }?.name ?? String(move.typeId) }
            catch { typeName = "无法读取" }
        }
    }
}

/// 编辑器的模态选择器，点选的编号直接写入配置，没有复制规则或内置假条目。
@MainActor struct KnowledgePicker: View {
    let knowledge: KnowledgeStore
    let kind: CatalogKind
    let select: (Int64) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var pokemon: [PokemonSummary] = []
    @State private var moves: [MoveDetails] = []
    @State private var failed = false
    /// knowledge 是只读知识源，kind 决定表，select 在主线程回传所选的真实 ID。
    var body: some View {
        NavigationStack {
            List {
                if failed { Text("无法读取离线图鉴") }
                if kind == .pokemon {
                    ForEach(pokemon) { item in Button { select(item.id); dismiss() } label: { CatalogRow(title: item.name, identifier: item.identifier, id: item.id, icon: .pokemon(item.id)) }.accessibilityIdentifier("choose-pokemon-\(item.id)") }
                } else {
                    ForEach(moves) { item in Button { select(item.id); dismiss() } label: { CatalogRow(title: item.name, identifier: item.identifier, id: item.id, icon: .elementType(item.typeId)) }.accessibilityIdentifier("choose-move-\(item.id)") }
                }
            }.searchable(text: $query, prompt: "名称、英文或编号").navigationTitle("选择\(kind.rawValue)")
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
                .task(id: query) {
                    do {
                        if kind == .pokemon { let result = try await knowledge.searchPokemon(query); try Task.checkCancellation(); pokemon = result }
                        else { let result = try await knowledge.searchMoves(query); try Task.checkCancellation(); moves = result }
                        failed = false
                    } catch is CancellationError { } catch { failed = true }
                }
        }
    }
}

/// 六项能力仅按固定字段展示，所有计算数值由知识库或 Core 返回。
@MainActor struct StatSummary: View {
    let values: StatValues
    /// 为能力值/种族值提供相同可访问标签。
    var body: some View {
        LabeledContent("HP", value: String(values.hp)); LabeledContent("攻击", value: String(values.attack))
        LabeledContent("防御", value: String(values.defense)); LabeledContent("特攻", value: String(values.specialAttack))
        LabeledContent("特防", value: String(values.specialDefense)); LabeledContent("速度", value: String(values.speed))
    }
}
