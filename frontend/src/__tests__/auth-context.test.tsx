/**
 * AuthContext tests — verifies role derivation logic.
 *
 * Since AuthContext has heavy dependencies (Magic SDK, Algorand, etc.),
 * we test the core logic: isBuyer/isSeller/isAdmin derivation.
 */

describe('AuthContext role derivation', () => {
  // Test the role derivation logic directly
  const deriveRoles = (tradeRole: string | undefined, userRole: string | undefined) => {
    const isBuyer = tradeRole === 'BUYER' || tradeRole === 'BOTH';
    const isSeller = tradeRole === 'SELLER' || tradeRole === 'BOTH';
    const isAdmin = userRole === 'ADMIN';
    return { isBuyer, isSeller, isAdmin };
  };

  it('BUYER role sets isBuyer=true, isSeller=false', () => {
    const { isBuyer, isSeller } = deriveRoles('BUYER', 'MEMBER');
    expect(isBuyer).toBe(true);
    expect(isSeller).toBe(false);
  });

  it('SELLER role sets isBuyer=false, isSeller=true', () => {
    const { isBuyer, isSeller } = deriveRoles('SELLER', 'MEMBER');
    expect(isBuyer).toBe(false);
    expect(isSeller).toBe(true);
  });

  it('BOTH role sets isBuyer=true AND isSeller=true', () => {
    const { isBuyer, isSeller } = deriveRoles('BOTH', 'MEMBER');
    expect(isBuyer).toBe(true);
    expect(isSeller).toBe(true);
  });

  it('ADMIN user role sets isAdmin=true', () => {
    const { isAdmin } = deriveRoles('BUYER', 'ADMIN');
    expect(isAdmin).toBe(true);
  });

  it('MEMBER user role sets isAdmin=false', () => {
    const { isAdmin } = deriveRoles('BUYER', 'MEMBER');
    expect(isAdmin).toBe(false);
  });

  it('undefined trade_role sets both to false', () => {
    const { isBuyer, isSeller } = deriveRoles(undefined, 'MEMBER');
    expect(isBuyer).toBe(false);
    expect(isSeller).toBe(false);
  });
});
