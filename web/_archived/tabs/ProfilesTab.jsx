export default function ProfilesTab() {
  return (
    <div id="tab-profiles" className="tab-content">
      <div id="tab-profiles-budget" className="section-subtab active">
                {/* Budget Calculator & Cost Tracking (from analytics-cost) */}
                <div className="settings-section" style={{borderLeft: '3px solid var(--warn)'}}>
                    <h3>⚠️ Cost & Token Burn Alerts</h3>
                    <p className="small">Set thresholds to receive alerts when costs or token consumption spike or sustain high rates.</p>

                    <div className="input-row">
                        <div className="input-group">
                            <label>Cost Spike Alert (USD/hour)</label>
                            <input type="number" id="alert_cost_burn_spike_usd_per_hour" min="0.01" max="100" step="0.01" placeholder="0.10" />
                            <p className="small" style={{color: 'var(--fg-muted)', marginTop: '4px'}}>Alert when hourly burn exceeds this amount</p>
                        </div>
                        <div className="input-group">
                            <label>Token Spike (tokens/min)</label>
                            <input type="number" id="alert_token_burn_spike_per_minute" min="100" max="100000" step="100" placeholder="5000" />
                            <p className="small" style={{color: 'var(--fg-muted)', marginTop: '4px'}}>Alert on sudden spike above this rate</p>
                        </div>
                    </div>

                    <div className="input-row">
                        <div className="input-group">
                            <label>Token Burn Sustained (tokens/min)</label>
                            <input type="number" id="alert_token_burn_sustained_per_minute" min="100" max="100000" step="100" placeholder="2000" />
                            <p className="small" style={{color: 'var(--fg-muted)', marginTop: '4px'}}>Alert if sustained for 15+ minutes</p>
                        </div>
                    </div>
                </div>

                {/* Budget Alerts */}
                <div className="settings-section" style={{borderLeft: '3px solid var(--accent)'}}>
                    <h3>💰 Budget Alerts</h3>
                    <p className="small">Set monthly budget limits and warning thresholds.</p>

                    <div className="input-row">
                        <div className="input-group">
                            <label>Monthly Budget (USD)</label>
                            <input type="number" id="alert_monthly_budget_usd" min="1" max="10000" step="1" placeholder="500" />
                            <p className="small" style={{color: 'var(--fg-muted)', marginTop: '4px'}}>Hard limit for monthly spending</p>
                        </div>
                        <div className="input-group">
                            <label>Budget Warning Level (USD)</label>
                            <input type="number" id="alert_budget_warning_usd" min="1" max="10000" step="1" placeholder="400" />
                            <p className="small" style={{color: 'var(--fg-muted)', marginTop: '4px'}}>Alert when spending exceeds this</p>
                        </div>
                    </div>

                    <div className="input-row">
                        <div className="input-group">
                            <label>Budget Critical Level (USD)</label>
                            <input type="number" id="alert_budget_critical_usd" min="1" max="10000" step="1" placeholder="450" />
                            <p className="small" style={{color: 'var(--fg-muted)', marginTop: '4px'}}>Critical alert when spending exceeds this</p>
                        </div>
                    </div>
                </div>

                {/* Storage Calculator */}
                <div id="storage-calculator-container"></div>
                </div>

                <div id="tab-profiles-management" className="section-subtab">
                    {/* Profile Management (from settings-profiles) */}
                    <div className="settings-section" style={{borderLeft: '3px solid var(--link)'}}>
                        <h3>💾 Configuration Profiles</h3>
                        <p className="small">Save and load configuration profiles</p>
                        {/* Legacy profile controls removed */}
                    </div>
                    {/* Save Alert Thresholds */}
                    <div className="settings-section">
                        <div className="input-row">
                            <button className="small-button" id="btn-save-alert-thresholds" style={{background: 'var(--accent)', color: 'var(--accent-contrast)', fontWeight: 600, width: '100%'}}>💾 Save Alert Thresholds</button>
                        </div>
                        <div id="alert-save-status" style={{fontSize: '12px', color: 'var(--fg-muted)', marginTop: '8px'}}></div>
                    </div>
                </div>

                <div id="tab-profiles-overrides" className="section-subtab">
                    <div className="settings-section" style={{borderLeft: '3px solid var(--accent)'}}>
                        <h3>Channel Overrides</h3>
                        <p className="small">HTTP, MCP, and CLI model overrides live under Admin → Integrations. Use the button below to jump there.</p>
                        <button className="small-button" id="btn-open-admin-integrations" style={{background: 'var(--link)', color: 'var(--accent-contrast)', fontWeight:600}}>Open Admin → Integrations</button>
                    </div>
                </div>
    </div>
  );
}
