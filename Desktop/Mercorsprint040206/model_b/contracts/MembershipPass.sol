// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title MembershipPass
 * @notice Non-transferable ERC-721 minted to subscribers after a successful
 *         Stripe subscription. One pass per address. Owner (backend wallet)
 *         is the only minter; revoke() lets the owner burn a pass if a
 *         subscription is cancelled or charged back.
 *
 * Deploy to Base (chainId 8453) via:
 *   npx thirdweb deploy
 */
contract MembershipPass is ERC721, Ownable {
    uint256 private _nextId;
    string private _uri;

    /// @notice Whether an address currently holds a pass.
    mapping(address => bool) public hasPass;
    /// @notice Token id held by an address (valid only while hasPass is true).
    mapping(address => uint256) public tokenOf;

    error AlreadyMember();
    error NotMember();
    error Soulbound();

    event MembershipMinted(address indexed to, uint256 indexed tokenId);
    event MembershipRevoked(address indexed from, uint256 indexed tokenId);

    constructor(
        string memory baseURI,
        address initialOwner
    ) ERC721("Membership Pass", "MEMBER") Ownable(initialOwner) {
        _uri = baseURI;
    }

    /// @notice Mint a pass to `to`. Backend-only (called from Stripe webhook).
    function ownerMint(address to) external onlyOwner returns (uint256) {
        if (hasPass[to]) revert AlreadyMember();
        uint256 tokenId = _nextId++;
        hasPass[to] = true;
        tokenOf[to] = tokenId;
        _safeMint(to, tokenId);
        emit MembershipMinted(to, tokenId);
        return tokenId;
    }

    /// @notice Burn a member's pass (e.g. subscription cancelled).
    function revoke(uint256 tokenId) public onlyOwner {
        address holder = _ownerOf(tokenId);
        hasPass[holder] = false;
        delete tokenOf[holder];
        _burn(tokenId);
        emit MembershipRevoked(holder, tokenId);
    }

    /// @notice Burn the pass held by `holder`. Convenience for the backend.
    function revokeFrom(address holder) external onlyOwner {
        if (!hasPass[holder]) revert NotMember();
        revoke(tokenOf[holder]);
    }

    function setBaseURI(string calldata uri) external onlyOwner {
        _uri = uri;
    }

    function _baseURI() internal view override returns (string memory) {
        return _uri;
    }

    /// @dev Soulbound: block transfers between non-zero addresses.
    function _update(
        address to,
        uint256 tokenId,
        address auth
    ) internal override returns (address) {
        address from = _ownerOf(tokenId);
        if (from != address(0) && to != address(0)) revert Soulbound();
        return super._update(to, tokenId, auth);
    }
}
