/**
 * C 端标签中英文映射
 *
 * 用法：
 *   import { t } from './translations.js';
 *   t.bodyPart('waist')       // '腰部'
 *   t.equipment('body weight') // '自重'
 *   t.target('abs')            // '腹肌'
 *
 * 字典查不到的词会原样返回英文），方便后续扩展
 */

// ---------- 身体部位 ----------
const BODY_PART = {
    'waist': '腰部',
    'chest': '胸部',
    'back': '背部',
    'shoulders': '肩部',
    'upper arms': '上臂',
    'lower arms': '前臂',
    'upper legs': '大腿',
    'lower legs': '小腿',
    'cardio': '有氧',
    'neck': '颈部',
};

// ---------- 器械 ----------
const EQUIPMENT = {
    'body weight': '自重',
    'dumbbell': '哑铃',
    'barbell': '杠铃',
    'cable': '绳索机',
    'leverage machine': '杠杆机',
    'band': '弹力带',
    'smith machine': '史密斯机',
    'kettlebells': '壶铃',
    'kettlebell': '壶铃',
    'weighted': '负重',
    'stability ball': '稳定球',
    'ez barbell': 'EZ 杠铃',
    'olympic barbell': '奥杆',
    'medicine ball': '药球',
    'roller': '泡沫轴',
    'rope': '绳索',
    'sled machine': '雪橇机',
    'wheel roller': '腹肌轮',
    'tire': '轮胎',
    'stepmill machine': '踏步机',
    'stationary bike': '动感单车',
    'elliptical machine': '椭圆机',
    'upper body ergometer': '上肢测力计',
};

// ---------- 目标肌肉 ----------
const TARGET = {
    'abs': '腹肌',
    'pectorals': '胸肌',
    'pectoralis major': '胸大肌',
    'lats': '背阔肌',
    'delts': '三角肌',
    'deltoids': '三角肌',
    'biceps': '肱二头肌',
    'triceps': '肱三头肌',
    'forearms': '前臂',
    'wrist flexors': '腕屈肌',
    'wrist extensors': '腕伸肌',
    'quads': '股四头肌',
    'quadriceps': '股四头肌',
    'hamstrings': '腘绳肌',
    'calves': '小腿',
    'gastrocnemius': '腓肠肌',
    'soleus': '比目鱼肌',
    'glutes': '臀肌',
    'gluteus maximus': '臀大肌',
    'adductors': '内收肌',
    'abductors': '外展肌',
    'hip flexors': '屈髋肌',
    'lower back': '下背',
    'spine': '脊柱',
    'trapezius': '斜方肌',
    'traps': '斜方肌',
    'rhomboids': '菱形肌',
    'levator scapulae': '肩胛提肌',
    'serratus anterior': '前锯肌',
    'obliques': '腹斜肌',
    'core': '核心',
    'ankle stabilizers': '踝稳定肌',
    'hands': '手部',
    'wrists': '手腕',
    'shoulders': '肩部',
    'neck': '颈部',
    'calves': '小腿',
    'ankles': '踝关节',
    'hip abductors': '髋外展',
    'hip adductors': '髋内收',
    'chest': '胸肌',
    'inner chest': '中胸',
    'upper chest': '上胸',
    'lower chest': '下胸',
    'upper back': '上背',
    'middle back': '中背',
    'upper abs': '上腹',
    'lower abs': '下腹',
    'side abs': '侧腹',
    'quads and calves': '大腿和小腿',
    'hip': '髋部',
    'shoulders and chest': '肩胸',
    'shoulders and triceps': '肩和三头',
    'shoulders and back': '肩和背',
    'biceps and forearms': '二头和前臂',
    'back and biceps': '背和二头',
    'chest and shoulders': '胸和肩',
    'chest and triceps': '胸和三头',
    'quadriceps and hamstrings': '股四头和腘绳肌',
    'lower abs and obliques': '下腹和腹斜',
    'glutes and hamstrings': '臀和腘绳',
    'inner thighs': '大腿内侧',
    'outer thighs': '大腿外侧',
    'chest and front delts': '胸和前三角',
    'shoulders and arms': '肩和手臂',
    'lats and triceps': '背阔和三头',
    'spinal erectors': '竖脊肌',
    'abdominals': '腹肌',
    'rotator cuff': '肩袖肌群',
};

// 兜底：如果字典里没有，返回原文（小写归一化匹配）
function lookup(dict, key) {
    if (!key) return '';
    const k = key.toLowerCase().trim();
    return dict[k] || key;
}

export const t = {
    bodyPart: (key) => lookup(BODY_PART, key),
    equipment: (key) => lookup(EQUIPMENT, key),
    target: (key) => lookup(TARGET, key),
};