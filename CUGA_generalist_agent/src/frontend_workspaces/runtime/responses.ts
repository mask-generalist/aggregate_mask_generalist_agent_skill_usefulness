
/**
 * Describes a command response.
 */
export class Response<TResponse> {
  constructor(
    public id: string,
    public data?: TResponse,
    public error?: any // Error class is not serializeable
  ) {}
}

