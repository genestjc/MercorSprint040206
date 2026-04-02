// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title MembershipPass
 * @notice ERC-721 membership token. One pass per address, minted by the
 *         backend when a Stripe subscription's first invoice is paid,
 *         and revoked (burned) when the subscription is canceled.
 *
 * @dev Deploy via ThirdWeb dashboard or `npx thirdweb deploy`.
 *      The deployer becomes the owner; transfer ownership to your backend
 *      signer wallet so the Stripe webhook can call mint/revoke.
 *
 *      Frontend access check:
 *        balanceOf(user) > 0  →  has access
 *
 *      Backend (in webhook):
 *        contract.mint(walletAddress)   // on invoice.paid
 *        contract.revoke(walletAddress) // on subscription.deleted
 */
contract MembershipPass is ERC721, Ownable {
    uint256 private _nextTokenId;

    /// @notice Maps a member's address to their token ID (0 = not a member).
    mapping(address => uint256) public memberToken;

    event Minted(address indexed to, uint256 indexed tokenId);
    event Revoked(address indexed from, uint256 indexed tokenId);

    constructor(
        address initialOwner
    ) ERC721("Membership Pass", "PASS") Ownable(initialOwner) {}

    /**
     * @notice Mint a membership pass to `to`. Reverts if already a member.
     * @dev Only callable by owner (your backend signer).
     */
    function mint(address to) external onlyOwner returns (uint256) {
        require(memberToken[to] == 0, "MembershipPass: already a member");
        uint256 tokenId = ++_nextTokenId;
        memberToken[to] = tokenId;
        _safeMint(to, tokenId);
        emit Minted(to, tokenId);
        return tokenId;
    }

    /**
     * @notice Burn `member`'s pass. Called when their subscription is canceled.
     * @dev Only callable by owner.
     */
    function revoke(address member) external onlyOwner {
        uint256 tokenId = memberToken[member];
        require(tokenId != 0, "MembershipPass: not a member");
        delete memberToken[member];
        _burn(tokenId);
        emit Revoked(member, tokenId);
    }

    /// @notice Convenience view for the frontend.
    function isMember(address account) external view returns (bool) {
        return memberToken[account] != 0;
    }

    /**
     * @dev Soulbound: passes cannot be transferred or sold. Only mint
     *      (from == 0) and burn (to == 0) are permitted. This keeps access
     *      strictly tied to the paying account — a user can't sell their
     *      pass to someone who isn't subscribed.
     *
     *      `_update` is OpenZeppelin v5's single transfer hook covering
     *      mint, burn, transfer, and safeTransfer in one place.
     */
    function _update(
        address to,
        uint256 tokenId,
        address auth
    ) internal override returns (address) {
        address from = _ownerOf(tokenId);
        require(
            from == address(0) || to == address(0),
            "MembershipPass: soulbound"
        );
        return super._update(to, tokenId, auth);
    }

    /**
     * @dev Soulbound tokens cannot have approvals. Reverts unless clearing
     *      (approving address(0)), which OZ does internally during burn.
     */
    function _approve(
        address to,
        uint256 tokenId,
        address auth,
        bool emitEvent
    ) internal override {
        require(to == address(0), "MembershipPass: soulbound");
        super._approve(to, tokenId, auth, emitEvent);
    }

    /// @dev Block operator approvals entirely.
    function setApprovalForAll(address, bool) public pure override {
        revert("MembershipPass: soulbound");
    }
}
