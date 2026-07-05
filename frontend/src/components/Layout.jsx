import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-gray-100">
      <nav className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center space-x-4">
              <Link to="/catalog" className="text-xl font-bold text-indigo-600">
                RCC
              </Link>
              <Link to="/catalog" className="text-gray-700 hover:text-indigo-600 px-3 py-2 text-sm">
                Catalog
              </Link>
              <Link to="/products" className="text-gray-700 hover:text-indigo-600 px-3 py-2 text-sm">
                Products
              </Link>
              <Link to="/orders" className="text-gray-700 hover:text-indigo-600 px-3 py-2 text-sm">
                Orders
              </Link>
            </div>
            <div className="flex items-center space-x-4">
              {user && (
                <span className="text-sm text-gray-600">
                  {user.username}
                </span>
              )}
              <button
                onClick={handleLogout}
                className="text-sm text-red-600 hover:text-red-800"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </nav>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  );
}
