import { uuidv4 } from "./functions";

export enum CommandType {
  RenderSidepanel = "nl2ui.sidepanel.render",
}

export class RenderSidepanelCommand implements Command {
  type: string = CommandType.RenderSidepanel;
  id: string = uuidv4();

  constructor() {}
}

/**
 * Describes a command.
 */
export interface Command {
  id: string;
  type: string;
  //message?: string; This may not be right in same time commenting it may break stuff
}