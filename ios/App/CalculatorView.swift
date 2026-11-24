import SwiftUI
import PokemonAppSupport

/// 配置编辑与真实计算入口；输入绑定只保存用户选择，不执行战斗公式。
@MainActor struct CalculatorView: View {
    @ObservedObject var model: AppModel
    let knowledge: KnowledgeStore
    @State private var attackerName = ""
    @State private var defenderName = ""
    @State private var moveName = ""
    @State private var selecting: SelectionTarget?
    @FocusState private var editingName: Bool
    /// 模态选择目标带独立身份，关闭后不重复呈现。
    private enum SelectionTarget: String, Identifiable { case attacker, defender, move; var id: String { rawValue } }
    /// Form 在 iPad 保留易读宽度，重计算期间只禁用输入区域，取消按钮保持可用。
    var body: some View {
        NavigationStack {
            Form {
                Group {
                    Section("配置") {
                        TextField("配置名称", text: $model.configuration.name).focused($editingName)
                            .submitLabel(.done).onSubmit { editingName = false }.accessibilityIdentifier("configuration-name")
                    }
                    Section("攻击方") {
                        Button(attackerName.isEmpty ? "选择宝可梦" : attackerName) { selecting = .attacker }.accessibilityIdentifier("select-attacker")
                        PokemonEditor(value: $model.configuration.attacker, natures: model.natures, prefix: "attacker")
                    }
                    Section("防御方") {
                        Button(defenderName.isEmpty ? "选择宝可梦" : defenderName) { selecting = .defender }.accessibilityIdentifier("select-defender")
                        PokemonEditor(value: $model.configuration.defender, natures: model.natures, prefix: "defender")
                    }
                    Section("招式与环境") {
                        Button(moveName.isEmpty ? "选择招式" : moveName) { selecting = .move }.accessibilityIdentifier("select-move")
                        Stepper("世代：\(model.configuration.generationId)", value: $model.configuration.generationId, in: 3...9)
                        Picker("天气", selection: $model.configuration.weather) { ForEach(WeatherRule.allCases, id: \.self) { Text($0.displayName).tag($0) } }
                        Picker("场地", selection: $model.configuration.terrain) { ForEach(TerrainRule.allCases, id: \.self) { Text($0.displayName).tag($0) } }
                        Toggle("击中要害", isOn: $model.configuration.critical)
                    }
                }.disabled(model.busy)
                Section {
                    Button("离线计算") { model.calculate(online: false) }.accessibilityIdentifier("calculate-offline").disabled(model.busy || model.knowledgeUpdateBusy)
                    Button("在线计算") { model.calculate(online: true) }.accessibilityIdentifier("calculate-online").disabled(model.busy || model.knowledgeUpdateBusy)
                    if model.busy {
                        ProgressView("计算中")
                        Button("取消计算", role: .cancel) { model.cancelCalculation() }
                    }
                    if !model.calculationMessage.isEmpty { Text(model.calculationMessage).accessibilityIdentifier("calculation-status") }
                }
                if let result = model.result { CalculationResultView(result: result, source: model.calculationSource) }
                Section("保存") {
                    Button("保存配置") { Task { await model.saveConfiguration() } }.accessibilityIdentifier("save-configuration").disabled(model.busy)
                    Button("另存为新配置") { Task { await model.saveConfiguration(asNew: true) } }.disabled(model.busy)
                    if !model.savedMessage.isEmpty { Text(model.savedMessage).accessibilityIdentifier("configuration-save-status") }
                }
            }.scrollDismissesKeyboard(.interactively).navigationTitle("战斗计算")
                .onChange(of: model.configuration) { _ in model.invalidateResult() }
                .sheet(item: $selecting) { target in
                    KnowledgePicker(knowledge: knowledge, kind: target == .move ? .move : .pokemon) { id in
                        switch target {
                        case .attacker: model.configuration.attacker.pokemonId = id
                        case .defender: model.configuration.defender.pokemonId = id
                        case .move: model.configuration.moveId = id
                        }
                    }
                }
                .task(id: "\(model.dataVersion)|\(model.configuration.attacker.pokemonId)|\(model.configuration.defender.pokemonId)|\(model.configuration.moveId)") { await loadNames() }
        }
    }
    /// 读取当前三个知识编号的真实名称；取消过期任务后禁止写回旧名字。
    private func loadNames() async {
        do {
            let attacker = try await knowledge.pokemon(model.configuration.attacker.pokemonId)
            let defender = try await knowledge.pokemon(model.configuration.defender.pokemonId)
            let move = try await knowledge.move(model.configuration.moveId)
            try Task.checkCancellation()
            attackerName = attacker.summary.name; defenderName = defender.summary.name; moveName = move.name
        } catch is CancellationError { } catch { model.present(error) }
    }
}

/// 单只宝可梦的输入控件；范围只约束单个输入，EV 总量及规则合法性仍交给 Core。
@MainActor private struct PokemonEditor: View {
    @Binding var value: PokemonConfiguration
    let natures: [NatureDetails]
    let prefix: String
    /// value 是可编辑完整配置，natures 来自当前知识包，prefix 区分双方的测试标识。
    var body: some View {
        Stepper("等级：\(value.level)", value: $value.level, in: 1...100)
        Picker("性格", selection: $value.natureId) { ForEach(natures) { Text($0.name).tag($0.id) } }
        DisclosureGroup("个体值") { StatEditor(values: $value.ivs, range: 0...31) }
        DisclosureGroup("努力值") { StatEditor(values: $value.evs, range: 0...252) }
        Picker("计算特性", selection: $value.ability) { ForEach(AbilityRule.allCases, id: \.self) { Text($0.displayName).tag($0) } }
        Picker("携带道具", selection: $value.item) { ForEach(ItemRule.allCases, id: \.self) { Text($0.displayName).tag($0) } }
        Toggle("麻痹", isOn: $value.paralyzed).accessibilityIdentifier("\(prefix)-paralyzed")
    }
}

/// 六项用户数值的明确绑定；不以字典或反射重建模型。
@MainActor private struct StatEditor: View {
    @Binding var values: StatValues
    let range: ClosedRange<Int>
    /// values 直接回写输入，range 由 IV/EV 编辑入口提供。
    var body: some View {
        Stepper("HP：\(values.hp)", value: $values.hp, in: range)
        Stepper("攻击：\(values.attack)", value: $values.attack, in: range)
        Stepper("防御：\(values.defense)", value: $values.defense, in: range)
        Stepper("特攻：\(values.specialAttack)", value: $values.specialAttack, in: range)
        Stepper("特防：\(values.specialDefense)", value: $values.specialDefense, in: range)
        Stepper("速度：\(values.speed)", value: $values.speed, in: range)
    }
}

/// 原样呈现 Core 精确分数与离散伤害；min/max 仅归纳返回的伤害数组用于显示。
@MainActor private struct CalculationResultView: View {
    let result: CalculationResult
    let source: CalculationSource?
    /// result 是一次完整实际调用的不可变结果，展开内容包含能力和计算版本。
    var body: some View {
        Section("计算结果") {
            if let source { metric("计算来源", value: source.displayName, identifier: "calculation-source") }
            metric("伤害", value: "\(result.damage.rolls.min() ?? 0)–\(result.damage.rolls.max() ?? 0)", identifier: "damage-range")
            metric("一击 KO", value: result.damage.ohko.text, identifier: "ohko-probability")
            metric("两击 KO", value: result.damage.twoHit.text, identifier: "two-hit-probability")
            metric("攻击方速度", value: String(result.attackerSpeed), identifier: "attacker-speed")
            LabeledContent("防御方速度", value: String(result.defenderSpeed))
            DisclosureGroup("全部伤害分布") { Text(result.damage.rolls.map(String.init).joined(separator: ", ")).font(.caption).textSelection(.enabled) }
            DisclosureGroup("攻击方能力") { StatSummary(values: result.attackerStats) }
            DisclosureGroup("防御方能力") { StatSummary(values: result.defenderStats) }
            metric("引擎版本", value: result.engineVersion, identifier: "calculation-engine-version")
            metric("规则版本", value: result.rulesVersion, identifier: "calculation-rules-version")
            metric("知识版本", value: result.knowledgeVersion, identifier: "calculation-knowledge-version")
        }
    }
    /// title 为指标名称，value 为 Core 结果的精确展示，identifier 是稳定控件标识。
    /// 返回独立名称/值的无障碍行，VoiceOver 与黑盒测试都无需从合并字符串猜测数值。
    private func metric(_ title: String, value: String, identifier: String) -> some View {
        LabeledContent(title, value: value).accessibilityElement(children: .ignore)
            .accessibilityLabel(title).accessibilityValue(value).accessibilityIdentifier(identifier)
    }
}

/// 以下映射只翻译固定合同标识，不赋予名称任何额外规则。
extension AbilityRule {
    /// 当前直接伤害实现的可读名称。
    var displayName: String {
        switch self { case .none: "不应用特性"; case .technician: "技术高手"; case .adaptability: "适应力"; case .thickFat: "厚脂肪"; case .filter: "过滤"; case .solidRock: "坚硬岩石"; case .sniper: "狙击手" }
    }
}
/// 当前道具合同的中文展示。
extension ItemRule {
    /// 只转换名称，实际效果由 Core 决定。
    var displayName: String {
        switch self { case .none: "无"; case .lifeOrb: "生命宝珠"; case .choiceBand: "讲究头带"; case .choiceSpecs: "讲究眼镜"; case .expertBelt: "达人带"; case .eviolite: "进化奇石" }
    }
}
/// 天气选择器名称。
extension WeatherRule {
    /// 只转换固定合同标识。
    var displayName: String { switch self { case .none: "无"; case .harshSunlight: "大晴天"; case .rain: "下雨"; case .sandstorm: "沙暴"; case .hail: "冰雹"; case .snow: "下雪" } }
}
/// 场地选择器名称。
extension TerrainRule {
    /// 只转换固定合同标识。
    var displayName: String { switch self { case .none: "无"; case .electric: "电气场地"; case .psychic: "精神场地"; case .grassy: "青草场地"; case .misty: "薄雾场地" } }
}
/// 图鉴的招式分类名称。
extension MoveCategory {
    /// 固定知识分类的中文标签。
    var displayName: String { switch self { case .physical: "物理"; case .special: "特殊"; case .status: "变化" } }
}
