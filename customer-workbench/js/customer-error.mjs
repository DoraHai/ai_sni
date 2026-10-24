const labels={
  SCOPE_MISMATCH:'返回数据超出当前客户或网站范围，已阻止显示，请重新读取',
  SCOPE_REQUIRED:'请先选择已授权的客户和网站',
  CONTEXT_CHANGED:'客户或网站已切换，请重新读取当前页面',
  AUTH_EXPIRED:'登录已失效，请重新登录',
  PERMISSION_DENIED:'当前账号没有读取权限，请核对授权',
  CONTRACT_MISMATCH:'返回数据格式不完整，已停止显示，请稍后重试',
  CONTENT_NOT_VERIFIED:'请先从当前网站的内容列表打开稿件',
  INVALID_PAGINATION:'分页参数无效，请返回列表重新读取',
  INVALID_FILTER:'筛选条件无效，请调整后重试',
};
export function customerErrorLabel(error){
  if(error?.name==='TimeoutError')return '读取超时，请点重新读取';
  if(error?.name==='AbortError')return '读取已中止，请点重新读取';
  const code=error?.code||error?.message;
  return Object.hasOwn(labels,code)?labels[code]+'（'+code+'）':'';
}
