import { useState, useEffect, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import AdminLayout from '../../components/AdminLayout';
import api from '../../lib/axios';

function formatCredits(n) {
  if (n == null) return '0.00';
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function AdminResellerDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [reseller, setReseller] = useState(null);
  const [orders, setOrders] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('orders');

  // Modals
  const [showCreditsModal, setShowCreditsModal] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [creditForm, setCreditForm] = useState({ amount: '', reason: 'Admin top-up' });
  const [passwordForm, setPasswordForm] = useState({ password: '' });
  const [actionLoading, setActionLoading] = useState(false);
  const [alert, setAlert] = useState(null);

  const fetchReseller = useCallback(async () => {
    try {
      const [resellerRes, ordersRes, transactionsRes] = await Promise.all([
        api.get(`/dashboard/resellers/${id}/`),
        api.get(`/dashboard/resellers/${id}/orders/`),
        api.get(`/dashboard/resellers/${id}/transactions/`),
      ]);
      setReseller(resellerRes.data);
      setOrders(ordersRes.data.results || ordersRes.data);
      setTransactions(transactionsRes.data.results || transactionsRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchReseller();
  }, [fetchReseller]);

  const showAlert = (msg, type = 'success') => {
    setAlert({ msg, type });
    setTimeout(() => setAlert(null), 4000);
  };

  const handleCreditAdjust = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.post(`/dashboard/resellers/${id}/credits/`, {
        amount: parseFloat(creditForm.amount),
        reason: creditForm.reason,
      });
      setShowCreditsModal(false);
      setCreditForm({ amount: '', reason: 'Admin top-up' });
      showAlert('Credits updated successfully!');
      fetchReseller();
    } catch (err) {
      showAlert(err.response?.data?.error || 'Failed to adjust credits.', 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handlePasswordReset = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.put(`/dashboard/resellers/${id}/`, { password: passwordForm.password });
      setShowPasswordModal(false);
      setPasswordForm({ password: '' });
      showAlert('Password updated successfully!');
    } catch (err) {
      showAlert(err.response?.data?.error || 'Failed to reset password.', 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleToggle = async () => {
    try {
      await api.post(`/dashboard/resellers/${id}/toggle/`);
      showAlert(`Reseller ${reseller.is_active ? 'deactivated' : 'activated'}.`);
      fetchReseller();
    } catch (err) {
      showAlert('Failed to toggle status.', 'error');
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('This will deactivate the reseller account. Continue?')) return;
    try {
      await api.delete(`/dashboard/resellers/${id}/`);
      navigate('/admin/resellers');
    } catch (err) {
      showAlert('Failed to delete reseller.', 'error');
    }
  };

  if (loading) {
    return (
      <AdminLayout>
        <div className="admin-loading">
          <div className="admin-spinner"></div>
          Loading reseller...
        </div>
      </AdminLayout>
    );
  }

  if (!reseller) {
    return (
      <AdminLayout>
        <div className="admin-empty">
          <div className="admin-empty-icon">❌</div>
          <div className="admin-empty-text">Reseller not found</div>
          <Link to="/admin/resellers" className="admin-btn admin-btn-primary">Back to Resellers</Link>
        </div>
      </AdminLayout>
    );
  }

  const statusBadge = reseller.is_active ? (
    <span className="admin-badge green">● Active</span>
  ) : (
    <span className="admin-badge red">● Inactive</span>
  );

  return (
    <AdminLayout>
      <Link to="/admin/resellers" style={{ fontSize: 14, color: '#6366f1', textDecoration: 'none', marginBottom: 16, display: 'inline-block' }}>
        ← Back to Resellers
      </Link>

      {alert && (
        <div className={`admin-alert ${alert.type}`}>
          {alert.type === 'success' ? '✅' : '⚠️'} {alert.msg}
        </div>
      )}

      {/* Profile + Stats */}
      <div className="admin-profile-grid">
        <div className="admin-card admin-profile-card">
          <div className="admin-profile-avatar">
            {reseller.username.charAt(0).toUpperCase()}
          </div>
          <div className="admin-profile-name">{reseller.username}</div>
          <div className="admin-profile-meta">
            {statusBadge}
            <div style={{ marginTop: 8 }}>Joined {new Date(reseller.date_joined).toLocaleDateString()}</div>
            {reseller.created_by_username && (
              <div style={{ marginTop: 4, fontSize: 12 }}>Created by {reseller.created_by_username}</div>
            )}
          </div>
          <div className="admin-profile-stats">
            <div>
              <div className="admin-profile-stat-label">Credits</div>
              <div className="admin-profile-stat-value">{formatCredits(reseller.credit_balance)}</div>
            </div>
            <div>
              <div className="admin-profile-stat-label">Orders</div>
              <div className="admin-profile-stat-value">{reseller.order_count || 0}</div>
            </div>
            <div>
              <div className="admin-profile-stat-label">Revenue</div>
              <div className="admin-profile-stat-value">{formatCredits(reseller.total_revenue)}</div>
            </div>
            <div>
              <div className="admin-profile-stat-label">UUID</div>
              <div style={{ fontSize: 11, color: '#64748b', wordBreak: 'break-all' }}>
                {reseller.uuid?.slice(0, 8)}...
              </div>
            </div>
          </div>
        </div>

        <div>
          {/* Action Buttons */}
          <div className="admin-card" style={{ marginBottom: 20 }}>
            <div className="admin-card-body" style={{ padding: 16 }}>
              <div className="admin-actions">
                <button className="admin-btn admin-btn-primary" onClick={() => setShowCreditsModal(true)}>
                  💰 Add/Remove Credits
                </button>
                <button className="admin-btn admin-btn-secondary" onClick={() => setShowPasswordModal(true)}>
                  🔒 Reset Password
                </button>
                <button
                  className={`admin-btn ${reseller.is_active ? 'admin-btn-danger' : 'admin-btn-success'}`}
                  onClick={handleToggle}
                >
                  {reseller.is_active ? '🔴 Deactivate' : '🟢 Activate'}
                </button>
                <button className="admin-btn admin-btn-danger" onClick={handleDelete}>
                  🗑️ Delete
                </button>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="admin-card">
            <div className="admin-tabs">
              <button
                className={`admin-tab ${activeTab === 'orders' ? 'active' : ''}`}
                onClick={() => setActiveTab('orders')}
              >
                📦 Orders ({orders.length})
              </button>
              <button
                className={`admin-tab ${activeTab === 'transactions' ? 'active' : ''}`}
                onClick={() => setActiveTab('transactions')}
              >
                💳 Credit History ({transactions.length})
              </button>
            </div>

            {activeTab === 'orders' && (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Order</th>
                      <th>Product</th>
                      <th>Qty</th>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.length === 0 ? (
                      <tr>
                        <td colSpan="6" style={{ textAlign: 'center', color: '#94a3b8', padding: 32 }}>
                          No orders yet
                        </td>
                      </tr>
                    ) : (
                      orders.map(o => (
                        <tr key={o.id}>
                          <td style={{ fontSize: 12, color: '#6366f1', fontFamily: 'monospace' }}>
                            {o.uuid?.slice(0, 8)}
                          </td>
                          <td style={{ fontWeight: 500 }}>{o.product_name_at_purchase}</td>
                          <td>{o.quantity}</td>
                          <td style={{ fontWeight: 500 }}>{formatCredits(o.total_credits)}</td>
                          <td>
                            <span className={`admin-badge ${
                              o.status === 'COMPLETED' ? 'green' :
                              o.status === 'FAILED' ? 'red' :
                              o.status === 'REFUNDED' ? 'amber' : 'blue'
                            }`}>
                              {o.status}
                            </span>
                          </td>
                          <td style={{ fontSize: 13, color: '#64748b' }}>
                            {new Date(o.created_at).toLocaleString()}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {activeTab === 'transactions' && (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Amount</th>
                      <th>Type</th>
                      <th>Reason</th>
                      <th>Balance After</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.length === 0 ? (
                      <tr>
                        <td colSpan="5" style={{ textAlign: 'center', color: '#94a3b8', padding: 32 }}>
                          No transactions yet
                        </td>
                      </tr>
                    ) : (
                      transactions.map(t => (
                        <tr key={t.id}>
                          <td style={{ fontSize: 13, color: '#64748b' }}>
                            {new Date(t.created_at).toLocaleString()}
                          </td>
                          <td style={{
                            fontWeight: 600,
                            color: Number(t.delta) >= 0 ? '#059669' : '#dc2626',
                          }}>
                            {Number(t.delta) >= 0 ? '+' : ''}{formatCredits(t.delta)}
                          </td>
                          <td>
                            <span className={`admin-badge ${t.actor === 'ADMIN' ? 'blue' : t.actor === 'SYSTEM' ? 'gray' : 'amber'}`}>
                              {t.actor}
                            </span>
                          </td>
                          <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {t.reason}
                          </td>
                          <td style={{ fontWeight: 500 }}>{formatCredits(t.balance_after)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Credits Modal */}
      {showCreditsModal && (
        <div className="admin-modal-overlay" onClick={() => setShowCreditsModal(false)}>
          <div className="admin-modal" onClick={e => e.stopPropagation()}>
            <div className="admin-modal-header">
              <div className="admin-modal-title">💰 Adjust Credits</div>
              <button className="admin-modal-close" onClick={() => setShowCreditsModal(false)}>✕</button>
            </div>
            <form onSubmit={handleCreditAdjust}>
              <div className="admin-modal-body">
                <p style={{ fontSize: 14, color: '#64748b', marginBottom: 16 }}>
                  Current balance: <strong>{formatCredits(reseller.credit_balance)}</strong>
                </p>
                <div className="admin-field">
                  <label className="admin-label">Amount (positive to add, negative to deduct) *</label>
                  <input
                    type="number"
                    step="0.01"
                    className="admin-input"
                    required
                    value={creditForm.amount}
                    onChange={e => setCreditForm(f => ({ ...f, amount: e.target.value }))}
                    placeholder="e.g. 100 or -50"
                  />
                </div>
                <div className="admin-field">
                  <label className="admin-label">Reason *</label>
                  <input
                    type="text"
                    className="admin-input"
                    required
                    value={creditForm.reason}
                    onChange={e => setCreditForm(f => ({ ...f, reason: e.target.value }))}
                  />
                </div>
              </div>
              <div className="admin-modal-footer">
                <button type="button" className="admin-btn admin-btn-secondary" onClick={() => setShowCreditsModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="admin-btn admin-btn-primary" disabled={actionLoading}>
                  {actionLoading ? 'Processing...' : '💰 Apply'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Password Modal */}
      {showPasswordModal && (
        <div className="admin-modal-overlay" onClick={() => setShowPasswordModal(false)}>
          <div className="admin-modal" onClick={e => e.stopPropagation()}>
            <div className="admin-modal-header">
              <div className="admin-modal-title">🔒 Reset Password</div>
              <button className="admin-modal-close" onClick={() => setShowPasswordModal(false)}>✕</button>
            </div>
            <form onSubmit={handlePasswordReset}>
              <div className="admin-modal-body">
                <div className="admin-field">
                  <label className="admin-label">New Password *</label>
                  <input
                    type="password"
                    className="admin-input"
                    required
                    minLength={6}
                    value={passwordForm.password}
                    onChange={e => setPasswordForm({ password: e.target.value })}
                    placeholder="Min 6 characters"
                  />
                </div>
              </div>
              <div className="admin-modal-footer">
                <button type="button" className="admin-btn admin-btn-secondary" onClick={() => setShowPasswordModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="admin-btn admin-btn-primary" disabled={actionLoading}>
                  {actionLoading ? 'Updating...' : '🔒 Reset Password'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AdminLayout>
  );
}
