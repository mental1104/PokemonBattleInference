# 旧 `/v1/damage` 独立合同

新纯领域与 codec 已独立验证；公开ABI注册、统一版本与HTTP接线由下一集成批完成。不能把当前文件存在视为旧HTTP已经修复。

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

证据 `p3-server-20261124/legacy-domain/`：GoogleTest2项、原真实AbilityFactory/责任链369例逐字段差分；同样2项和369例在新增领域/codec ASAN+UBSAN构建上通过。覆盖全部25性格/null、随机舍入边界及相邻值、非5倍等级、非4倍/超过现代上限EV、负等级/负EV、status/负威力、免疫/双属性和超过2**53的数值。原public NameError另存`legacy-damage/legacy-origin.json`，不把修复前原500冒称正常计算oracle。
