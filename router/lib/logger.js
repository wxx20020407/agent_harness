/**
 * Logger - 结构化日志工具
 *
 * 输出格式：JSON Lines，便于日志收集和分析
 */

class Logger {
  constructor(context = 'Router') {
    this.context = context;
  }

  /**
   * 格式化日志条目
   */
  format(level, message, data = {}) {
    const entry = {
      timestamp: new Date().toISOString(),
      level,
      context: this.context,
      message,
      ...data
    };
    return JSON.stringify(entry);
  }

  info(message, data = {}) {
    console.log(this.format('INFO', message, data));
  }

  warn(message, data = {}) {
    console.warn(this.format('WARN', message, data));
  }

  error(message, data = {}) {
    console.error(this.format('ERROR', message, data));
  }

  debug(message, data = {}) {
    if (process.env.LOG_LEVEL === 'debug') {
      console.log(this.format('DEBUG', message, data));
    }
  }

  /**
   * 创建子 logger
   */
  child(subContext) {
    return new Logger(`${this.context}:${subContext}`);
  }

  /**
   * 请求日志中间件
   */
  requestLogger() {
    return (req, res, next) => {
      const start = Date.now();
      const requestId = req.id;

      this.info('Request started', {
        requestId,
        method: req.method,
        path: req.path,
        ip: req.ip
      });

      // 响应完成时记录
      res.on('finish', () => {
        const duration = Date.now() - start;
        this.info('Request completed', {
          requestId,
          method: req.method,
          path: req.path,
          statusCode: res.statusCode,
          duration: `${duration}ms`
        });
      });

      next();
    };
  }
}

// 导出单例
export const logger = new Logger('Router');
export default Logger;
