/** 为 Vitest 样式合同测试声明 Vite raw CSS 导入结果。 */
declare module '*.css?raw' {
  const content: string;
  export default content;
}
