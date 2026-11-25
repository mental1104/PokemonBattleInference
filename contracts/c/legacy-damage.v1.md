# 旧 `/v1/damage` 独立合同

纯领域、codec和正式0.9 ABI已验证；旧HTTP通过独立子进程调用此操作，独立空PG验收见下文。

当前旧Python router 调用已删除且未导入的 `PokemonDirector`，合法请求真实返回500/NameError。此次保留旧伤害/历史构造行为并修复该故障，不把旧路由转发成现代 `/calculator/damage`。

正式操作形态：

```json
{
  "kind": "legacy_damage",
  "attacker": {
    "level": 100,
    "base": [100,100,100,100,100,100],
    "basepoint": [0,252,0,0,0,0],
    "nature": "Adamant",
    "types": [1]
  },
  "defender": {
    "level": 100,
    "base": [100,100,100,100,100,100],
    "basepoint": [252,0,252,0,0,0],
    "nature": "Impish",
    "types": [12,9]
  },
  "move": {"power":80,"type":1,"move_type":"physical_move"},
  "random_unit": 0.5,
  "type_chart": [{"attacking":1,"defending":12,"percent":100},{"attacking":1,"defending":9,"percent":50}]
}
```

`base`固定六轴HP/Atk/Def/SpAtk/SpDef/Speed；basepoint不足六项按旧`CommonProperty.create`拒绝，额外项忽略，没有新加现代EV总量/等级约束。nature使用原25个首字母大写英文枚举或null；Quiet故意保留原Speed=1.0。原HTTP的`individual_values`从未传给director，实际全部使用31，因此该输入字段不进入Core构造事实。外层保留原公开字段，不能偷偷开始采用用户IV。

属性表由拥有者注入，需与原`domain.models.types.type_efficacy`核对。未知知识不默认为中性。`random_unit`为平台提供的有限[0,1]事实；Core执行原uniform→Python两位round→逐链int，平台不计算伤害或随机倍率。旧公式、旧EV/4浮点、Quiet、逐阶段int和percent向下截一位均不改变现代能力/伤害/回合入口。

返回字段为 `kind,formula,min_damage,max_damage,random_damage,min_damage_percent,max_damage_percent,random_damage_percent,attacker_stats,defender_stats,random_multiplier`。三个伤害整数及两组六能力采用十进制字符串，避免任意精度整数被JSON浮点化；百分比和随机倍率为原binary64值。外层旧HTTP只投影原七字段，把三项伤害作为真正JSON整数输出；额外准备证据不泄漏到旧DTO。formula原行为始终空字符串。

纯领域入口 `CalculateLegacyStats` / `CalculateLegacyDamage`，正式codec `ReadLegacyDamageRequest` / `EvaluateLegacyDamage`。源 `core/src/legacy_damage.cpp` 不查询数据库、不产生随机数、不调用现代伤害公式。

原 `Type` 枚举仅1..18，没有UNKNOWN成员。旧19×19矩阵的0行/列为内部空属性哨兵，不能据此接受公开`Unknown`/`Stellar`：原`Type.from_string`实际均抛ValueError。固定全量CSV的Pokemon属性无0、无18以外值、无缺失slot1。Go保留实际类型ID和槽位，不删除未知类型或改成Normal；坏槽位显式拒绝，未来类型交Core明确拒绝，不声称任意损坏知识均兼容。

证据 `p3-server-20261124/legacy-domain/`：GoogleTest2项、原真实AbilityFactory/责任链369例逐字段差分；同样2项和369例在新增领域/codec ASAN+UBSAN构建上通过。覆盖全部25性格/null、随机舍入边界及相邻值、非5倍等级、非4倍/超过现代上限EV、负等级/负EV、status/负威力、免疫/双属性和超过2**53的数值。原public NameError另存`legacy-damage/legacy-origin.json`，不把修复前原500冒称正常计算oracle。

Release `-O3 -DNDEBUG -Werror`曾触发Boost小整数左移的GCC14 stringop-overflow告警；有限binary64指数范围内改为最多53次bit_set构造，不关闭告警。最终2原生/369原Python差分全部通过（`release-o3-bitset.log`），源SHA256为`796d5869caacd3714a2400c10d31fd7681cc74808efd46698b255145b15a414f`。

`legacy-http-final/`从自有空PG纯Go导入完整CSV，真实API→独立0.9 child验收33/33、零SKIP（4.62秒），包括旧接口19项与现代calculator14项。旧接口恢复历史构造后比较原责任链；随机两字段验证属于原随机输出支持集，不声称两次独立随机抽样逐值相同。现代14项全部完整JSON等价，含原两项静态动态特性缺口。真实全图鉴资料测试及11个schema子场景race/vet通过；脚本退出清理自有PG/API。
