import React from "react";
import { Shield, CheckCircle, Settings, Hash, Type, Database, ExternalLink } from "lucide-react";

export default function ToolCallFlowDisplay({ toolData }) {
  const toolCallData = toolData;

  const getArgIcon = (key, value) => {
    if (typeof value === "number") return <Hash className="w-3 h-3 text-blue-500" />;
    if (typeof value === "string") return <Type className="w-3 h-3 text-green-500" />;
    return <Database className="w-3 h-3 text-gray-500" />;
  };

  const formatArgValue = (value) => {
    if (typeof value === "string") return `"${value}"`;
    return String(value);
  };

  return (
    <div className="p-4">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-lg shadow-md border p-4">
          {/* Header with trust indicator */}
          <div className="flex items-center gap-3 mb-4">
            {toolCallData.name != "run_new_flow" && (
              <div className="flex items-center gap-2">
                <Shield className="w-5 h-5 text-emerald-600" />
                <CheckCircle className="w-4 h-4 text-emerald-500" />
              </div>
            )}
            <h2 className="text-lg font-semibold text-gray-800"></h2>
          </div>

          {/* Flow content */}
          <div className="space-y-4">
            {/* Function name */}
            <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg p-4 border border-blue-100">
              <div className="flex items-center gap-2 mb-2">
                <Settings className="w-4 h-4 text-blue-600" />
                <span className="text-sm font-medium text-blue-800">Flow Name</span>
              </div>
              <div className="font-mono text-lg font-semibold text-blue-900 bg-white px-3 py-2 rounded border">
                {toolCallData.name}
              </div>
            </div>

            {/* Arguments */}
            <div className="bg-gradient-to-r from-green-50 to-emerald-50 rounded-lg p-4 border border-green-100">
              <div className="flex items-center gap-2 mb-3">
                <Database className="w-4 h-4 text-green-600" />
                <span className="text-sm font-medium text-green-800">Inputs</span>
              </div>
              <div className="space-y-2">
                {Object.entries(toolCallData.args).map(([key, value]) => (
                  <div key={key} className="bg-white rounded border p-3 flex items-center gap-3">
                    {getArgIcon(key, value)}
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-semibold text-gray-700">{key}:</span>
                        <span className="font-mono text-sm text-gray-900 bg-gray-50 px-2 py-1 rounded">
                          {formatArgValue(value)}
                        </span>
                      </div>
                    </div>
                    <div className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">{typeof value}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Trust indicator footer with Flow explained button */}
            {toolCallData.name != "run_new_flow" && (
              <div className="flex items-center justify-between pt-2 border-t border-gray-100">
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-emerald-500" />
                  <span className="text-sm text-gray-600">Verified and trusted flow</span>
                </div>
                <button
                  className="flex items-center gap-2 px-3 py-1.5 text-sm text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-md transition-colors duration-200 border border-blue-200 hover:border-blue-300"
                  onClick={() => {
                    try {
                      window.open(`${API_BASE_URL}/flows/flow.html`, "_blank");
                    } catch (error) {
                      alert("Local server not running. Please start your development server.");
                    }
                  }}
                >
                  <span>Flow explained</span>
                  <ExternalLink className="w-3 h-3" />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
