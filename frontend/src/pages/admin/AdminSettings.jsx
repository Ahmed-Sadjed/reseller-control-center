import { useState, useEffect } from 'react';
import AdminLayout from '../../components/AdminLayout';
import api from '../../lib/axios';

export default function AdminSettings() {
  const [whatsappPhone, setWhatsappPhone] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [alert, setAlert] = useState(null);

  useEffect(() => {
    api.get('/dashboard/settings/')
      .then(res => setWhatsappPhone(res.data.whatsapp_phone || ''))
      .catch(() => setAlert({ msg: 'Failed to load settings.', type: 'error' }))
      .finally(() => setLoading(false));
  }, []);

  const showAlert = (msg, type = 'success') => {
    setAlert({ msg, type });
    setTimeout(() => setAlert(null), 3000);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.put('/dashboard/settings/', { whatsapp_phone: whatsappPhone });
      showAlert('WhatsApp number saved!');
    } catch {
      showAlert('Failed to save.', 'error');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <AdminLayout>
        <div className="admin-loading"><div className="admin-spinner"></div> Loading...</div>
      </AdminLayout>
    );
  }

  return (
    <AdminLayout>
      <h1 style={{ fontSize: 24, fontWeight: 700, color: '#1e293b', marginBottom: 8 }}>⚙️ Settings</h1>
      <p style={{ fontSize: 14, color: '#64748b', marginBottom: 24 }}>Configure your admin preferences</p>

      {alert && (
        <div className={`admin-alert ${alert.type}`} style={{ marginBottom: 16 }}>
          {alert.type === 'success' ? '✅' : '⚠️'} {alert.msg}
        </div>
      )}

      <div className="admin-card">
        <div className="admin-card-body">
          <form onSubmit={handleSave}>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: '#1e293b', marginBottom: 16 }}>💬 WhatsApp Notifications</h2>
            <p style={{ fontSize: 13, color: '#64748b', marginBottom: 16 }}>
              When a WhatsApp product is purchased, a pre-filled message link will be generated using this number.
            </p>
            <div className="admin-field">
              <label className="admin-label">Your WhatsApp Number</label>
              <input
                type="text"
                className="admin-input"
                placeholder="e.g. 2126XXXXXXX"
                value={whatsappPhone}
                onChange={e => setWhatsappPhone(e.target.value)}
                style={{ maxWidth: 300 }}
              />
              <p style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
                Digits only with country code. You can include + and spaces — they'll be stripped automatically. Example: 213556471889
              </p>
            </div>
            <button type="submit" className="admin-btn admin-btn-primary" disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </button>
          </form>
        </div>
      </div>
    </AdminLayout>
  );
}
