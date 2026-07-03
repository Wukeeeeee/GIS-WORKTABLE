var greetings = {
  dawn: [
    '夜深了，早点休息',
    '凌晨了，还没睡呢',
    '这么晚了，注意身体',
  ],
  morning: [
    '早上好，今天打算构建什么',
    '早上好，开始今天的工作吧',
    '早啊，准备好开工了吗',
    '早上好，新的一天开始了',
  ],
  forenoon: [
    '上午好，有什么需要帮忙的吗',
    '上午好，GIS 时间到了',
    '上午好，正在处理什么数据',
  ],
  noon: [
    '中午好，先吃个饭吧',
    '中午好，休息一下再继续',
    '中午了，歇一会儿吧',
  ],
  afternoon: [
    '下午好，进度还顺利吗',
    '下午好，继续加油',
    '下午好，有什么需要处理的',
  ],
  night: [
    '晚上好，还在工作呢',
    '晚上好，辛苦了',
    '晚上好，今天收获怎么样',
  ],
};

function randomPick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function updateGreeting() {
    var date = new Date();
    var hours = date.getHours();
    var minutes = date.getMinutes();
    var seconds = date.getSeconds();
    var ampm = hours >= 12 ? 'PM' : 'AM';
    var displayHours = hours % 12;
    displayHours = displayHours ? displayHours : 12;
    minutes = minutes < 10 ? '0' + minutes : minutes;
    seconds = seconds < 10 ? '0' + seconds : seconds;
    var strTime = displayHours + ':' + minutes + ':' + seconds + ' ' + ampm;

    var greeting = '';
    if (hours < 6) {
        greeting = randomPick(greetings.dawn);
    } else if (hours < 9) {
        greeting = randomPick(greetings.morning);
    } else if (hours < 12) {
        greeting = randomPick(greetings.forenoon);
    } else if (hours < 14) {
        greeting = randomPick(greetings.noon);
    } else if (hours < 18) {
        greeting = randomPick(greetings.afternoon);
    } else {
        greeting = randomPick(greetings.night);
    }

    var el = document.getElementsByClassName('chat-messages-empty')[0];
    if (el) el.textContent = greeting;
}

// 页面加载时执行
document.addEventListener('DOMContentLoaded', updateGreeting);