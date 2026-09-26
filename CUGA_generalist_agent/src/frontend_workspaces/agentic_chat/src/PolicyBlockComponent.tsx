import React from "react";
import { Shield, AlertCircle, Info } from "lucide-react";
import "./PolicyBlockComponent.css";

interface PolicyBlockData {
  type: "policy_block";
  content: string;
  metadata: {
    policy_blocked: boolean;
    policy_id: string;
    policy_name: string;
    policy_reasoning: string;
    policy_confidence: number;
  };
}

interface PolicyBlockComponentProps {
  data: PolicyBlockData;
}

const PolicyBlockComponent: React.FC<PolicyBlockComponentProps> = ({ data }) => {
  const { content, metadata } = data;
  const confidencePercent = Math.round(metadata.policy_confidence * 100);

  return (
    <div className="policy-block-container">
      <div className="policy-block-header">
        <div className="policy-block-icon">
          <Shield size={24} />
        </div>
        <div className="policy-block-title">
          <h3>Intent Blocked by Policy</h3>
          <span className="policy-block-badge">Security Policy</span>
        </div>
      </div>

      <div className="policy-block-content">
        <div className="policy-block-message">
          <AlertCircle size={18} className="message-icon" />
          <p>{content}</p>
        </div>

        <div className="policy-block-details">
          <div className="policy-detail-row">
            <span className="policy-detail-label">Policy Name:</span>
            <span className="policy-detail-value">{metadata.policy_name}</span>
          </div>
          
          <div className="policy-detail-row">
            <span className="policy-detail-label">Policy ID:</span>
            <span className="policy-detail-value policy-id">{metadata.policy_id}</span>
          </div>
          
          <div className="policy-detail-row">
            <span className="policy-detail-label">Match Confidence:</span>
            <div className="confidence-bar-container">
              <div className="confidence-bar">
                <div 
                  className="confidence-bar-fill" 
                  style={{ width: `${confidencePercent}%` }}
                />
              </div>
              <span className="confidence-value">{confidencePercent}%</span>
            </div>
          </div>

          <div className="policy-reasoning-section">
            <div className="reasoning-header">
              <Info size={16} />
              <span>Reasoning</span>
            </div>
            <p className="reasoning-text">{metadata.policy_reasoning}</p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PolicyBlockComponent;

