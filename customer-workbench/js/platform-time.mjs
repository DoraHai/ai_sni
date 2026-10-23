import {formatTime} from './customer-display.mjs';
export function platformTime(value){
  if(!value)return '暂无记录';
  const stamp=typeof value==='string'&&/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(value)?value+'Z':value;
  const text=formatTime(stamp);
  return text+(/时区未提供|时间待核对|时间未提供/.test(text)?'':'（北京时间）');
}
