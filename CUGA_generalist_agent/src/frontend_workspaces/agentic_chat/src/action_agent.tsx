import React, { useState } from "react";

interface AgentData {
  thoughts: string[];
  next_agent: string;
  instruction: string;
}

export default function AgentThoughtsComponent({ agentData }: { agentData: AgentData }) {
  const [showFullThoughts, setShowFullThoughts] = useState(false);

  // Sample data for demonstration

  // Use props if provided, otherwise use sample data
  const { thoughts, next_agent, instruction } = agentData;

  function getAgentColor(agentName: string) {
    const colors: { [key: string]: string } = {
      ActionAgent: "bg-blue-100 text-blue-800 border-blue-300",
      ValidationAgent: "bg-green-100 text-green-800 border-green-300",
      NavigationAgent: "bg-purple-100 text-purple-800 border-purple-300",
      AnalysisAgent: "bg-yellow-100 text-yellow-800 border-yellow-300",
      TestAgent: "bg-orange-100 text-orange-800 border-orange-300",
    };
    return colors[agentName] || "bg-gray-100 text-gray-800 border-gray-300";
  }

  function getAgentIcon(agentName: string) {
    const icons: { [key: string]: string } = {
      ActionAgent: "🎯",
      QaAgent: "🔍",
    };
    return icons[agentName] || "🤖";
  }

  function truncateThoughts(thoughtsArray: string[], maxLength = 120) {
    const firstThought = thoughtsArray[0] || "";
    if (firstThought.length <= maxLength) return firstThought;
    return firstThought.substring(0, maxLength) + "...";
  }

  function truncateInstruction(instruction: string, maxLength = 80) {
    if (instruction.length <= maxLength) return instruction;
    return instruction.substring(0, maxLength) + "...";
  }

  return (
    <div className="p-3">
      <div className="max-w-3xl mx-auto">
        <div className="bg-white rounded-lg border border-gray-200 p-3">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <span className="text-base">🤖</span>
              Agent Workflow
            </h3>
            <span className="px-2 py-1 rounded text-xs bg-indigo-100 text-indigo-700">Processing</span>
          </div>

          {/* Next Agent */}
          <div className="mb-3 p-2 bg-gray-50 rounded border">
            <div className="flex items-center gap-2">
              <span className="text-sm">{getAgentIcon(next_agent)}</span>
              <span className="text-xs text-gray-600">Next:</span>
              <span className={`px-2 py-1 rounded text-xs font-medium ${getAgentColor(next_agent)}`}>
                {next_agent}
              </span>
            </div>
          </div>

          {/* Current Instruction */}
          <div className="mb-3 p-2 bg-blue-50 rounded border border-blue-200">
            <div className="flex items-start gap-2">
              <span className="text-sm">📋</span>
              <div className="flex-1">
                <p className="text-xs text-gray-600 mb-1">Current Instruction</p>
                <p className="text-xs text-gray-700 leading-relaxed">{truncateInstruction(instruction, 100)}</p>
              </div>
            </div>
          </div>

          {/* Thoughts Section - Collapsible */}
          <div className="border-t border-gray-100 pt-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">💭</span>
                <span className="text-xs text-gray-500">Analysis ({thoughts.length})</span>
                <button
                  onClick={() => setShowFullThoughts(!showFullThoughts)}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  {showFullThoughts ? "▲" : "▼"}
                </button>
              </div>
            </div>
            
            {!showFullThoughts && (
              <p className="text-xs text-gray-400 italic mt-1">{truncateThoughts(thoughts, 80)}</p>
            )}

            {showFullThoughts && (
              <div className="mt-2 space-y-1">
                {thoughts.map((thought: string, index: number) => (
                  <div key={index} className="flex items-start gap-2">
                    <span className="text-xs text-gray-300 mt-0.5 font-mono">{index + 1}.</span>
                    <p className="text-xs text-gray-500 leading-relaxed">{thought}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
