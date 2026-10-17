// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

/// @title KurStaking — staking/farming multi-pool da KuramaChain
/// @notice Cada pool aceita um token (KUR, LP token do DEX, etc.) e paga
///         recompensas em outro token a uma taxa por segundo. O modelo é o
///         clássico "accRewardPerShare" (MasterChef): o saldo de recompensa
///         de cada usuário é `amount * accRewardPerShare / 1e18 - rewardDebt`.
///
///         O owner cria o pool e mantém o contrato abastecido com o token de
///         recompensa (`fundPool`). A emissão para em `rewardEnd`; nada é
///         criado do nada — se o contrato não tiver saldo, `claim` reverte.
contract KurStaking {
    uint256 private constant ACC_PRECISION = 1e18;

    struct Pool {
        address stakingToken;
        address rewardToken;
        uint256 rewardRate;          // recompensa por segundo
        uint256 rewardEnd;           // timestamp em que a emissão para
        uint256 lastUpdate;
        uint256 accRewardPerShare;   // escalado por 1e18
        uint256 totalStaked;
        uint256 rewardBudget;        // recompensas disponíveis (nunca toca o principal)
        bool exists;
    }

    struct UserInfo {
        uint256 amount;       // tokens em stake
        uint256 rewardDebt;   // amount * accRewardPerShare / 1e18 no último settle
        uint256 pending;      // recompensas já consolidadas
    }

    address public owner;
    uint256 public poolCount;

    mapping(uint256 => Pool) public pools;
    mapping(uint256 => mapping(address => UserInfo)) public users;

    bool private _entered;

    event PoolCreated(uint256 indexed pid, address indexed stakingToken,
                      address indexed rewardToken, uint256 rewardRate, uint256 rewardEnd);
    event RewardRateUpdated(uint256 indexed pid, uint256 rewardRate, uint256 rewardEnd);
    event Staked(uint256 indexed pid, address indexed user, uint256 amount);
    event Withdrawn(uint256 indexed pid, address indexed user, uint256 amount);
    event RewardPaid(uint256 indexed pid, address indexed user, uint256 amount);
    event EmergencyWithdrawn(uint256 indexed pid, address indexed user, uint256 amount);
    event PoolFunded(uint256 indexed pid, address indexed from, uint256 amount);
    event OwnershipTransferred(address indexed from, address indexed to);

    modifier onlyOwner() {
        require(msg.sender == owner, 'KurStaking: NOT_OWNER');
        _;
    }

    modifier nonReentrant() {
        require(!_entered, 'KurStaking: REENTRANT');
        _entered = true;
        _;
        _entered = false;
    }

    modifier validPool(uint256 pid) {
        require(pools[pid].exists, 'KurStaking: NO_POOL');
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    // ─── Administração ───────────────────────────────────────────

    /// @notice Cria um pool de staking.
    /// @dev `stakingToken` pode ser igual a `rewardToken` (stake KUR → ganha
    ///      KUR): as recompensas saem do `rewardBudget` (abastecido via
    ///      `fundPool`), nunca do principal depositado.
    /// @param stakingToken Token depositado (KUR, LP token...).
    /// @param rewardToken Token pago como recompensa.
    /// @param rewardRate Recompensa por segundo (em unidades do rewardToken).
    /// @param rewardEnd Timestamp em que a emissão termina.
    function createPool(address stakingToken, address rewardToken,
                        uint256 rewardRate, uint256 rewardEnd)
        external onlyOwner returns (uint256 pid)
    {
        require(stakingToken != address(0), 'KurStaking: ZERO_ADDRESS');
        require(rewardToken != address(0), 'KurStaking: ZERO_ADDRESS');
        require(rewardEnd > block.timestamp || rewardRate == 0, 'KurStaking: BAD_END');

        pid = poolCount++;
        pools[pid] = Pool({
            stakingToken: stakingToken,
            rewardToken: rewardToken,
            rewardRate: rewardRate,
            rewardEnd: rewardEnd,
            lastUpdate: block.timestamp,
            accRewardPerShare: 0,
            totalStaked: 0,
            rewardBudget: 0,
            exists: true
        });
        emit PoolCreated(pid, stakingToken, rewardToken, rewardRate, rewardEnd);
    }

    /// @notice Atualiza a emissão do pool (consolida o acumulado antes).
    function setRewardRate(uint256 pid, uint256 rewardRate, uint256 rewardEnd)
        external onlyOwner validPool(pid)
    {
        require(rewardEnd > block.timestamp || rewardRate == 0, 'KurStaking: BAD_END');
        _updatePool(pid);
        Pool storage p = pools[pid];
        p.rewardRate = rewardRate;
        p.rewardEnd = rewardEnd;
        emit RewardRateUpdated(pid, rewardRate, rewardEnd);
    }

    /// @notice Abastece o orçamento de recompensas do pool.
    /// @dev Use `approve(staking, amount)` antes. O orçamento garante que o
    ///      principal em stake nunca seja pago como recompensa.
    function fundPool(uint256 pid, uint256 amount) external onlyOwner validPool(pid) {
        require(amount > 0, 'KurStaking: ZERO_AMOUNT');
        Pool storage p = pools[pid];
        require(IERC20(p.rewardToken).transferFrom(msg.sender, address(this), amount),
                'KurStaking: TRANSFER_FAILED');
        p.rewardBudget += amount;
        emit PoolFunded(pid, msg.sender, amount);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), 'KurStaking: ZERO_ADDRESS');
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // ─── Staking ─────────────────────────────────────────────────

    function stake(uint256 pid, uint256 amount) external validPool(pid) nonReentrant {
        require(amount > 0, 'KurStaking: ZERO_AMOUNT');
        Pool storage p = pools[pid];
        _settle(pid, msg.sender);

        require(IERC20(p.stakingToken).transferFrom(msg.sender, address(this), amount),
                'KurStaking: TRANSFER_FAILED');
        UserInfo storage u = users[pid][msg.sender];
        u.amount += amount;
        u.rewardDebt = u.amount * p.accRewardPerShare / ACC_PRECISION;
        p.totalStaked += amount;

        emit Staked(pid, msg.sender, amount);
    }

    function withdraw(uint256 pid, uint256 amount) external validPool(pid) nonReentrant {
        UserInfo storage u = users[pid][msg.sender];
        require(amount > 0 && amount <= u.amount, 'KurStaking: BAD_AMOUNT');
        Pool storage p = pools[pid];
        _settle(pid, msg.sender);

        u.amount -= amount;
        u.rewardDebt = u.amount * p.accRewardPerShare / ACC_PRECISION;
        p.totalStaked -= amount;

        require(IERC20(p.stakingToken).transfer(msg.sender, amount),
                'KurStaking: TRANSFER_FAILED');
        emit Withdrawn(pid, msg.sender, amount);
    }

    /// @notice Resgata as recompensas acumuladas.
    function claim(uint256 pid) external validPool(pid) nonReentrant returns (uint256 amount) {
        _settle(pid, msg.sender);
        UserInfo storage u = users[pid][msg.sender];
        amount = u.pending;
        require(amount > 0, 'KurStaking: NO_REWARD');
        u.pending = 0;

        Pool storage p = pools[pid];
        require(amount <= p.rewardBudget, 'KurStaking: REWARD_BUDGET_EXHAUSTED');
        p.rewardBudget -= amount;
        require(IERC20(p.rewardToken).transfer(msg.sender, amount),
                'KurStaking: TRANSFER_FAILED');
        emit RewardPaid(pid, msg.sender, amount);
    }

    /// @notice Sai do pool sem receber recompensas (usado se o reward token
    ///         estiver com problema). Devolve só o principal.
    function emergencyWithdraw(uint256 pid) external validPool(pid) nonReentrant {
        UserInfo storage u = users[pid][msg.sender];
        uint256 amount = u.amount;
        require(amount > 0, 'KurStaking: NOTHING_STAKED');

        Pool storage p = pools[pid];
        u.amount = 0;
        u.rewardDebt = 0;
        u.pending = 0;
        p.totalStaked -= amount;

        require(IERC20(p.stakingToken).transfer(msg.sender, amount),
                'KurStaking: TRANSFER_FAILED');
        emit EmergencyWithdrawn(pid, msg.sender, amount);
    }

    // ─── Consultas ───────────────────────────────────────────────

    /// @notice Recompensa disponível para `user` agora (inclui o accrual pendente).
    function pendingReward(uint256 pid, address user) external view validPool(pid)
        returns (uint256)
    {
        Pool storage p = pools[pid];
        UserInfo storage u = users[pid][user];
        uint256 acc = p.accRewardPerShare;
        uint256 total = p.totalStaked;
        if (total > 0 && block.timestamp > p.lastUpdate) {
            uint256 end = block.timestamp < p.rewardEnd ? block.timestamp : p.rewardEnd;
            if (end > p.lastUpdate) {
                acc += (end - p.lastUpdate) * p.rewardRate * ACC_PRECISION / total;
            }
        }
        return u.pending + u.amount * acc / ACC_PRECISION - u.rewardDebt;
    }

    function poolInfo(uint256 pid) external view returns (
        address stakingToken, address rewardToken, uint256 rewardRate,
        uint256 rewardEnd, uint256 totalStaked, uint256 accRewardPerShare,
        uint256 rewardBudget
    ) {
        Pool storage p = pools[pid];
        return (p.stakingToken, p.rewardToken, p.rewardRate, p.rewardEnd,
                p.totalStaked, p.accRewardPerShare, p.rewardBudget);
    }

    function userInfo(uint256 pid, address user) external view returns (
        uint256 amount, uint256 rewardDebt, uint256 pending
    ) {
        UserInfo storage u = users[pid][user];
        return (u.amount, u.rewardDebt, u.pending);
    }

    // ─── Internos ────────────────────────────────────────────────

    function _settle(uint256 pid, address user) internal {
        Pool storage p = pools[pid];
        _updatePool(pid);
        UserInfo storage u = users[pid][user];
        uint256 accumulated = u.amount * p.accRewardPerShare / ACC_PRECISION;
        u.pending += accumulated - u.rewardDebt;
        u.rewardDebt = accumulated;
    }

    function _updatePool(uint256 pid) internal {
        Pool storage p = pools[pid];
        if (block.timestamp <= p.lastUpdate) {
            return;
        }
        uint256 end = block.timestamp < p.rewardEnd ? block.timestamp : p.rewardEnd;
        if (end > p.lastUpdate && p.totalStaked > 0) {
            p.accRewardPerShare += (end - p.lastUpdate) * p.rewardRate
                                    * ACC_PRECISION / p.totalStaked;
        }
        p.lastUpdate = block.timestamp;
    }
}
