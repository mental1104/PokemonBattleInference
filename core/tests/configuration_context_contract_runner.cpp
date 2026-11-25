#include "../src/configuration_contract.hpp"
#include <iostream>

/// 无参数；正式context codec逐行入口，原始候选不经过测试适配器过滤/归并。
/// @return 流故障非零；领域失败保留原诊断，不能以更小候选空间伪装成功。
int main(){
 std::string line;
 while(std::getline(std::cin,line)){
  try{
   const auto request=pbi::contract::ReadConfigurationSpaceRequest(pbi::contract::Json::parse(line),{});
   std::cout<<pbi::contract::EvaluateConfigurationSpace(request,{}).dump()<<'\n';
  }catch(const std::exception& error){std::cout<<pbi::contract::Json{{"error",error.what()}}.dump()<<'\n';}
 }
 return std::cin.bad()||!std::cout?1:0;
}
